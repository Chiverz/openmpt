"""snes_spc700_platformer.py - Super Nintendo (SPC700 / S-DSP) bouncy overworld theme, in the style of
early-90s SNES platformers.

Chip:   Sony SPC700 + S-DSP: 8 voices of BRR-compressed samples at 32 kHz, Gaussian interpolation,
        and a hardware echo with feedback that gives SNES music its "wet" sound.
        Recreated with synthesized instruments run through mptscript.chip.brr() (real BRR 4-bit
        ADPCM encoding), rendered at 32 kHz with cubic interpolation (close to Gaussian), and
        OpenMPT's built-in DMO Echo plugin standing in for the S-DSP echo buffer.
Format: IT, 8 channels, with an effect plugin.
Tune:   original. F major, swung eighths (triplet grid: 6 rows per beat), ~160 BPM.

Run:  python -m mptscript run examples/chipsets/snes_spc700_platformer.py --play
"""

import math
import os
import random
from fractions import Fraction as F

import mptscript as mpt
from mptscript import chip, fx, notes, plugins
from mptscript.chip import FMOp, Wave
from mptscript.compose import line

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MPTSCRIPT_OUT", HERE)
SR = 32000
rnd = random.Random(1990)

# 6 rows per beat x speed 3 = 18 ticks per beat: tempo 120 gives 160 BPM.
song = mpt.Song.new("it", channels=8, title="Cloud Meadow Romp (S-DSP)", artist="mptscript", tempo=120, speed=3)
song.rows_per_beat, song.rows_per_measure = 6, 24
song.sample_preamp = 34
BAR = 24


def tone(fn, root, seconds, loop=None, name=""):
    """Render fn(t, f0) at the SNES rate as a one-shot pitched at `root`, then BRR-encode it."""
    f0 = notes.frequency(root)
    n = int(SR * seconds)
    data = [fn(i / SR, f0) for i in range(n)]
    peak = max(abs(v) for v in data) or 1
    w = Wave([v * 0.9 / peak for v in data], c5_speed=round(SR * chip.MIDDLE_C_HZ / f0), loop=loop, name=name,
             resampling="cubic")
    return chip.brr(w)


def marimba(t, f):
    return (math.sin(2 * math.pi * f * t) * math.exp(-t * 7)
            + 0.35 * math.sin(2 * math.pi * 4 * f * t) * math.exp(-t * 30)
            + 0.15 * math.sin(2 * math.pi * 10 * f * t) * math.exp(-t * 60))


def pizz(t, f):
    s = sum(math.sin(2 * math.pi * f * k * t) / k * math.exp(-t * (6 + 3 * k)) for k in range(1, 8))
    return s * min(1, t / 0.003)


def bass_fn(t, f):
    s = sum(math.sin(2 * math.pi * f * k * t) / k ** 1.3 * math.exp(-t * (3 + 2.5 * k)) for k in range(1, 7))
    return s * min(1, t / 0.002)


FLUTE_CYCLES, FLUTE_PERIOD = 64, 61  # loop of whole cycles keeps the sustain seamless


def flute_wave():
    f0 = SR / FLUTE_PERIOD  # ~524.6 Hz, i.e. about C-6
    attack = int(SR * 0.08)
    n = attack + FLUTE_CYCLES * FLUTE_PERIOD
    data = []
    for i in range(n):
        ph = i / FLUTE_PERIOD
        v = math.sin(2 * math.pi * ph) + 0.25 * math.sin(4 * math.pi * ph) + 0.08 * math.sin(6 * math.pi * ph)
        if i < attack:
            v = v * (i / attack) + 0.3 * (rnd.random() * 2 - 1) * (1 - i / attack)  # breathy chiff
        data.append(v * 0.6)
    w = Wave(data, c5_speed=round(SR * chip.MIDDLE_C_HZ / f0), loop=(attack, n), resampling="cubic", name="flute")
    return chip.brr(w)


def drum(kind):
    n = int(SR * {"kick": 0.3, "snare": 0.25, "hat": 0.06, "bongo": 0.18}[kind])
    out, ph = [], 0.0
    for i in range(n):
        t = i / SR
        if kind == "kick":
            ph += (50 + 120 * math.exp(-t * 35)) / SR
            v = math.sin(2 * math.pi * ph) * math.exp(-t * 9)
        elif kind == "snare":
            v = (0.6 * math.sin(2 * math.pi * 200 * t) * math.exp(-t * 30) + (rnd.random() * 2 - 1) * math.exp(-t * 14))
        elif kind == "hat":
            v = (rnd.random() * 2 - 1) * math.exp(-t * 70)
        else:
            ph += (420 + 200 * math.exp(-t * 60)) / SR
            v = math.sin(2 * math.pi * ph) * math.exp(-t * 22)
        out.append(v)
    peak = max(abs(v) for v in out)
    return chip.brr(Wave([v * 0.9 / peak for v in out], c5_speed=SR, name=kind, resampling="cubic"))


brass_raw = chip.fm([FMOp(1, 1.0, attack=0.02, decay=0.2, sustain=0.6), FMOp(1, 1.0, attack=0.02, decay=0.4, sustain=0.7),
                     FMOp(2, 0.4, attack=0.03, decay=0.2, sustain=0.5), FMOp(1, 0.8, attack=0.02, decay=0.4, sustain=0.6)],
                    algorithm=4, feedback=0.3, root="C-5", duration=0.6, target_rate=SR, name="brass")

# --- Echo (the S-DSP echo buffer): ~190 ms, feedback, mixed back in ------------------------------
echo = song.add_plugin("echo", wet_dry=0.28, feedback=0.42, left_delay=plugins.ms(190), right_delay=plugins.ms(190))

flute = song.add_instrument("Flute (BRR)", flute_wave(), volume=44, envelope=chip.adsr(2, 10, 50, 10),
                            vibrato=(14, 5, 50), plugin=echo)
mar = song.add_instrument("Marimba (BRR)", tone(marimba, "C-5", 0.7, name="marimba"), volume=40, plugin=echo)
piz = song.add_instrument("Pizzicato (BRR)", tone(pizz, "C-5", 0.45, name="pizzicato"), volume=30)
bas = song.add_instrument("Finger bass (BRR)", tone(bass_fn, "C-4", 0.6, name="bass"), volume=56)
brs = song.add_instrument("Brass (BRR)", chip.brr(brass_raw), volume=30, envelope=chip.adsr(1, 6, 40, 6), plugin=echo)
kick = song.add_instrument("Kick (BRR)", drum("kick"), volume=58)
snare = song.add_instrument("Snare (BRR)", drum("snare"), volume=44, plugin=echo)
hat = song.add_instrument("Hat (BRR)", drum("hat"), volume=22)
bongo = song.add_instrument("Bongo (BRR)", drum("bongo"), volume=34)

LEAD, MAR, PZ1, PZ2, BASS, DRUM, PERC, BRASS = range(8)
for ch, (name, pan) in enumerate([("Flute", 128), ("Marimba", 176), ("Pizz 1", 80), ("Pizz 2", 176),
                                  ("Bass", 128), ("Kick/Snare", 128), ("Hats/Bongos", 160), ("Brass", 96)]):
    song.channels[ch].update(name=name, pan=pan)

S, L = F(1, 3), F(2, 3)  # swung eighths: short (2 rows) and long (4 rows)
PROG_A = [("F-2", ["A-4", "C-5", "F-5"]), ("D-2", ["A-4", "D-5", "F-5"]),
          ("Bb1", ["Bb4", "D-5", "F-5"]), ("C-2", ["Bb4", "C-5", "E-5"])]
PROG_B = [("Bb1", ["Bb4", "D-5", "F-5"]), ("A-1", ["A-4", "C#5", "E-5"]),
          ("D-2", ["A-4", "D-5", "F-5"]), ("G-1", ["Bb4", "D-5", "G-5"]), ]


def bassline(p, prog):
    """Swing walking bass: root, fifth, octave, approach."""
    for bar, (root, _) in enumerate(prog):
        r = notes.parse(root)
        steps = [(r, L), (r + 7, S), (r + 12, L), (r + 7, S), (r, L), (r + 7, S), (r + 10, L), (r + 11, S)]
        line(p, BASS, [(notes.name(n), b) for n, b in steps], bas, start=bar * BAR, rest="")


def pizzicato(p, prog):
    """Off-beat chord plucks on the swung 'and'."""
    for bar, (_, voicing) in enumerate(prog):
        for beat in range(4):
            row = bar * BAR + beat * 6 + 4
            p.set(row, PZ1, voicing[1], piz)
            p.set(row, PZ2, voicing[2], piz)


def drums(p, bars=4, fill=True):
    for bar in range(bars):
        base = bar * BAR
        for beat in range(4):
            row = base + beat * 6
            p.set(row, DRUM, "C-5", kick if beat % 2 == 0 else snare)
            p.set(row, PERC, "C-5", hat)
            p.set(row + 4, PERC, "C-5", hat, volume=14)
        if fill and bar == bars - 1:
            for k, row in enumerate(range(base + 12, base + 24, 2)):
                p.set(row, PERC, ["G-5", "E-5", "C-5", "G-5", "E-5", "C-5"][k], bongo)
            p.set(base + 22, DRUM, "C-5", snare)


MELODY_A = [("C-6", L), ("A-5", S), ("C-6", L), ("F-6", S), ("A-6", 1), ("G-6", L), ("F-6", S),
            ("D-6", L), ("F-6", S), ("A-6", L), ("D-7", S), ("C-7", 2),
            ("Bb6", L), ("A-6", S), ("G-6", L), ("F-6", S), ("D-6", L), ("F-6", S), ("Bb6", L), ("A-6", S),
            ("G-6", 3), ("r", 1)]
MELODY_B = [("D-7", 1), ("C-7", L), ("Bb6", S), ("F-6", 2),
            ("E-6", L), ("F-6", S), ("G-6", L), ("A-6", S), ("C#7", 2),
            ("D-7", L), ("C-7", S), ("A-6", L), ("F-6", S), ("D-6", 2),
            ("G-6", L), ("A-6", S), ("Bb6", L), ("D-7", S), ("C-7", 2)]


def counter(p, melody, transpose=-12):
    """Marimba answers the flute: same rhythm, an octave down, only on beats where the flute moves."""
    items = [(n if n == "r" else notes.name(notes.transpose(n, transpose)), b) for n, b in melody]
    line(p, MAR, items, mar, rest="")


def brass_hits(p, prog):
    for bar, (_, voicing) in enumerate(prog):
        p.set(bar * BAR, BRASS, voicing[2], brs)
        p.set(bar * BAR + 3, BRASS, "===")


intro = song.patterns[0]
intro.rows = 2 * BAR
intro.name = "intro"
line(intro, MAR, [("F-6", L), ("A-6", S), ("C-7", L), ("A-6", S), ("F-6", L), ("C-6", S), ("A-5", 1),
                  ("G-6", L), ("Bb6", S), ("C-7", L), ("E-6", S), ("G-6", 2)], mar, rest="")
brass_hits(intro, PROG_A[2:])
drums(intro, 2)

a = song.add_pattern(4 * BAR, name="A")
bassline(a, PROG_A)
pizzicato(a, PROG_A)
drums(a, fill=False)
line(a, LEAD, MELODY_A, flute)
brass_hits(a, PROG_A)

b = song.add_pattern(4 * BAR, name="B")
bassline(b, PROG_B)
pizzicato(b, PROG_B)
drums(b)
line(b, LEAD, MELODY_B, flute)
counter(b, MELODY_B)

a2 = song.duplicate_pattern(a)
a2.name = "A + marimba"
counter(a2, MELODY_A)

end = song.duplicate_pattern(b)
end.name = "B (loop)"
end.set_effect(end.rows - 1, BRASS, fx.position_jump(1))

song.order = [intro.index, a.index, b.index, a2.index, end.index]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    song.save(os.path.join(OUT, "snes_spc700_platformer.it"))
    print(song.render(os.path.join(OUT, "snes_spc700_platformer.wav"), samplerate=32000, interpolation="cubic"))
