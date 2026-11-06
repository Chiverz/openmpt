"""arena_anthem.py - an original early-90s Amiga "future sport" title theme, as a 4-channel ProTracker MOD.

Style notes, in the spirit of Bitmap Brothers-era Amiga title music:
  * hard breakbeat (kick + gated snare share one channel, as on a real 4-channel MOD)
  * acid-house bass with tone-portamento slides and a brighter accent sample
  * minor and major chord "orchestra" stabs
  * a detuned, chorused lead with vibrato on held notes
  * sci-fi laser zaps, crash, rising-noise whoosh and snare-roll builds

All samples are synthesized below at Amiga-friendly rates (8363 Hz x 2^n) and
stored as 8-bit, so the module plays in any ProTracker-compatible player.
The Amiga pans channels Left Right Right Left; OpenMPT's render emulates Paula
and the A500 output filter.

Patterns are 4 bars of 16 sixteenth-note rows at speed 6 / tempo 125 (125 BPM).
Note on pitch: ProTracker can only play notes C-4..B-6 (OpenMPT naming), so
each pitched sample has a "root"; melodies are written at real pitch and
shifted onto the sample (see Voice).

Run:  python -m mptscript run examples/arena_anthem.py --play
"""

import math
import os
import random

import mptscript as mpt
from mptscript import fx, notes
from mptscript.chip import Wave

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MPTSCRIPT_OUT", HERE)  # songs are written next to this script
rnd = random.Random(1990)

AMIGA_C5 = 8363            # ProTracker sample rate at C-5 (finetune 0)
PT_LOW, PT_HIGH = notes.parse("C-4"), notes.parse("B-6")


def rate_for(play_note: str) -> float:
    """Sample rate a sample must be rendered at so it plays back unpitched at `play_note`."""
    return AMIGA_C5 * 2 ** ((notes.parse(play_note) - notes.MIDDLE_C) / 12)


def hz(note: str) -> float:
    return notes.frequency(note)


# --- DSP helpers (pure Python) ---------------------------------------------------------
def saw(phase: float) -> float:
    return 2.0 * (phase % 1.0) - 1.0


def lowpass_svf(x, sr, cutoff, damping=0.5):
    """State-variable low-pass. cutoff: Hz constant or function of time in seconds."""
    low = band = 0.0
    out = []
    for i, s in enumerate(x):
        fc = cutoff(i / sr) if callable(cutoff) else cutoff
        f = 2.0 * math.sin(math.pi * min(fc, sr * 0.2) / sr)
        low += f * band
        high = s - low - damping * band
        band += f * high
        out.append(low)
    return out


def highpass(x, amount=1.0):
    out, prev = [], 0.0
    for s in x:
        out.append(s - amount * prev)
        prev = s
    return out


def normalise(x, peak=0.95):
    m = max(abs(v) for v in x) or 1.0
    return [v * peak / m for v in x]


def shape(x, drive=1.5):
    return [math.tanh(v * drive) for v in x]


def one_shot(data, sr, name):
    # Rendered at sr, played at the matching note; stored with the standard Amiga C-5 rate.
    return Wave(normalise(data), c5_speed=AMIGA_C5, name=name)


# --- Samples ---------------------------------------------------------------------------------
DRUM_SR = rate_for("C-6")  # 16726 Hz, drums are triggered on C-6


def make_kick():
    sr, n = DRUM_SR, int(DRUM_SR * 0.36)
    out, ph = [], 0.0
    for i in range(n):
        t = i / sr
        ph += (45 + 135 * math.exp(-t * 32)) / sr
        v = math.sin(2 * math.pi * ph) * math.exp(-t * 7.5)
        if t < 0.003:
            v += 0.6 * (rnd.random() * 2 - 1)
        out.append(v)
    return one_shot(shape(out, 1.8), sr, "kick")


def make_snare():
    sr, n = DRUM_SR, int(DRUM_SR * 0.26)
    noise = highpass([rnd.random() * 2 - 1 for _ in range(n)], 0.7)
    out = []
    for i in range(n):
        t = i / sr
        gate = 1.0 if t < 0.17 else max(0.0, 1 - (t - 0.17) / 0.04)  # gated-reverb style cut-off
        body = math.sin(2 * math.pi * 190 * t) * math.exp(-t * 28) * 0.8
        tail = noise[i] * (0.55 * math.exp(-t * 5) + 0.45 * math.exp(-t * 30))
        out.append((body + tail) * gate)
    return one_shot(shape(out, 1.4), sr, "snare gated")


def make_hat(open_=False):
    sr = DRUM_SR
    n = int(sr * (0.32 if open_ else 0.07))
    noise = highpass(highpass([rnd.random() * 2 - 1 for _ in range(n)]))
    k = 11 if open_ else 55
    return one_shot([v * math.exp(-i / sr * k) for i, v in enumerate(noise)], sr, "hat open" if open_ else "hat")


def make_crash():
    sr, n = DRUM_SR, int(DRUM_SR * 1.6)
    noise = highpass([rnd.random() * 2 - 1 for _ in range(n)], 0.85)
    return one_shot([v * math.exp(-i / sr * 2.6) for i, v in enumerate(noise)], sr, "crash")


def make_zap():
    sr, n = DRUM_SR, int(DRUM_SR * 0.34)
    out, ph = [], 0.0
    for i in range(n):
        t = i / sr
        ph += (110 + 2600 * math.exp(-t * 14)) / sr
        out.append((1.0 if ph % 1 < 0.5 else -1.0) * math.exp(-t * 5))
    return one_shot(lowpass_svf(out, sr, 3000, 0.7), sr, "laser zap")


def make_whoosh():
    """Rising filtered noise lasting one bar (16 rows at 125 BPM = 1.92 s)."""
    sr, dur = DRUM_SR, 1.92
    n = int(sr * dur)
    noise = [rnd.random() * 2 - 1 for _ in range(n)]
    filt = lowpass_svf(noise, sr, lambda t: 150 * (3300 / 150) ** (t / dur), 0.35)
    return one_shot([v * (i / n) ** 1.5 for i, v in enumerate(filt)], sr, "whoosh")


BASS_PLAY, BASS_ROOT = "F-5", "E-3"   # rendered at 11163 Hz; plays E-3 when triggered on F-5


def make_bass(accent=False):
    sr = rate_for(BASS_PLAY)
    n = int(sr * 0.42)
    f0 = hz(BASS_ROOT)
    top, bottom = (2900, 260) if accent else (1500, 180)
    raw = [saw(f0 * i / sr) + 0.5 * saw(f0 * 1.003 * i / sr) for i in range(n)]
    filt = lowpass_svf(raw, sr, lambda t: bottom + (top - bottom) * math.exp(-t * (9 if accent else 14)),
                       0.18 if accent else 0.3)
    env = [min(1.0, i / (sr * 0.002)) * (0.35 + 0.65 * math.exp(-i / sr * 6)) * (1 - i / n) ** 0.5 for i in range(n)]
    return one_shot(shape([a * b for a, b in zip(filt, env)], 2.2 if accent else 1.6), sr,
                    "acid bass acc" if accent else "acid bass")


STAB_PLAY, STAB_ROOT = "C-6", "E-5"   # chord stab rooted on E-5, triggered on C-6


def make_stab(major=False):
    sr = rate_for(STAB_PLAY)
    n = int(sr * 0.5)
    root = hz(STAB_ROOT)
    ratios = [0.5, 1.0, 2 ** ((4 if major else 3) / 12), 2 ** (7 / 12), 2.0]
    voices = [(root * r * d) for r in ratios for d in (0.995, 1.005)]
    raw = []
    for i in range(n):
        t = i / sr
        v = sum(saw(f * t) for f in voices) / len(voices)
        if t < 0.01:
            v += 0.4 * (rnd.random() * 2 - 1)
        raw.append(v)
    filt = lowpass_svf(raw, sr, lambda t: 700 + 2800 * math.exp(-t * 7), 0.4)
    env = [min(1.0, i / (sr * 0.003)) * math.exp(-i / sr * 5.5) for i in range(n)]
    return one_shot(shape([a * b for a, b in zip(filt, env)], 1.6), sr, "stab major" if major else "stab minor")


LEAD_PLAY, LEAD_ROOT = "C-6", "C-6"


def make_lead():
    """Seamless chorused loop: 4096 frames holding exactly 128 and 129 saw cycles plus a square."""
    sr = rate_for(LEAD_PLAY)
    L = 4096
    one = []
    for i in range(L):
        a = saw(128 * i / L)
        b = saw(129 * i / L)
        sq = 1.0 if (128 * i / L) % 1 < 0.5 else -1.0
        one.append(0.45 * a + 0.35 * b + 0.25 * sq)
    filt = lowpass_svf(one * 2, sr, 2600, 0.6)[L:]  # second period: filter state has settled
    return Wave(normalise(filt, 0.9), c5_speed=AMIGA_C5, loop=(0, L), name="lead chorus")


# --- Song setup ------------------------------------------------------------------------------
song = mpt.Song.new("mod", channels=4, title="Arena Anthem", tempo=125, speed=6)
DRUMS, PERC, BASS, LEAD = range(4)  # Amiga panning: L R R L

S = {
    "kick": song.add_instrument("kick", make_kick(), volume=64),
    "snare": song.add_instrument("snare gated", make_snare(), volume=58),
    "hat": song.add_instrument("hat", make_hat(), volume=26),
    "ohat": song.add_instrument("hat open", make_hat(True), volume=24),
    "crash": song.add_instrument("crash", make_crash(), volume=34),
    "zap": song.add_instrument("laser zap", make_zap(), volume=36),
    "whoosh": song.add_instrument("whoosh", make_whoosh(), volume=44),
    "bass": song.add_instrument("acid bass", make_bass(), volume=58),
    "bacc": song.add_instrument("acid bass acc", make_bass(True), volume=56),
    "stab": song.add_instrument("stab minor", make_stab(), volume=44),
    "stabM": song.add_instrument("stab major", make_stab(True), volume=44),
    "lead": song.add_instrument("lead chorus", make_lead(), volume=40),
}


class Voice:
    """Maps real pitches onto a sample's playable ProTracker note."""

    def __init__(self, sample, play, root):
        self.sample, self.offset = sample, notes.parse(play) - notes.parse(root)

    def note(self, real):
        n = notes.parse(real) + self.offset
        if not PT_LOW <= n <= PT_HIGH:
            raise ValueError(f"{real} is outside this sample's ProTracker range")
        return n


BASS_V = Voice(S["bass"], BASS_PLAY, BASS_ROOT)
BACC_V = Voice(S["bacc"], BASS_PLAY, BASS_ROOT)
LEAD_V = Voice(S["lead"], LEAD_PLAY, LEAD_ROOT)
STAB_MIN = Voice(S["stab"], STAB_PLAY, STAB_ROOT)
STAB_MAJ = Voice(S["stabM"], STAB_PLAY, STAB_ROOT)

CHORD = {"Em": ("E-5", STAB_MIN, "E-3", 3), "Am": ("A-4", STAB_MIN, "A-2", 3), "C": ("C-5", STAB_MAJ, "C-3", 4),
         "D": ("D-5", STAB_MAJ, "D-3", 4), "B": ("B-4", STAB_MAJ, "B-2", 4)}


def hit(p, row, ch, name, note="C-6", volume=None, effect=None):
    p.set(row, ch, note, S[name], volume, effect)


def stab(p, row, chord, ch=LEAD):
    root, voice, _, _ = CHORD[chord]
    p.set(row, ch, voice.note(root), voice.sample)


# --- Pattern parts -------------------------------------------------------------------------------
BREAK_A = "K..KS..K.KK.S..."
BREAK_B = "K..KS..K.KSsSsSS"
HATS = "h.hhh.h.h.hhh.o."
DRUM_MAP = {"K": ("kick", None), "S": ("snare", None), "s": ("snare", 30), "h": ("hat", None), "o": ("ohat", None)}


def beat(p, bars=4, fill=True, hats=True):
    for bar in range(bars):
        steps = BREAK_B if fill and bar == bars - 1 else BREAK_A
        for i, c in enumerate(steps):
            if c in DRUM_MAP:
                hit(p, bar * 16 + i, DRUMS, DRUM_MAP[c][0], volume=DRUM_MAP[c][1])
        if hats:
            for i, c in enumerate(HATS):
                if c in DRUM_MAP:
                    hit(p, bar * 16 + i, PERC, DRUM_MAP[c][0], volume=DRUM_MAP[c][1])


# Acid riff template per bar: semitone offsets from the chord root (None = rest).
RIFF = [0, None, 12, None, 0, 0, None, 12, None, 0, "3rd", None, 0, None, 7, "slide12"]


def bassline(p, chords):
    for bar, chord in enumerate(chords):
        _, _, root, third = CHORD[chord]
        for i, step in enumerate(RIFF):
            if step is None:
                continue
            row = bar * 16 + i
            effect = None
            if step == "3rd":
                semis = third
            elif step == "slide12":
                semis, effect = 12, fx.tone_porta(0x20)
            else:
                semis = step
            voice = BACC_V if semis == 12 else BASS_V
            p.set(row, BASS, voice.note(notes.name(notes.transpose(root, semis))), voice.sample, effect=effect)


def stabs(p, chords, rhythm="x..x..x...x.x..."):
    for bar, chord in enumerate(chords):
        for i, c in enumerate(rhythm):
            if c == "x":
                stab(p, bar * 16 + i, chord)


def melody(p, bars):
    """bars: strings of 16 tokens (real pitch, '.' hold, '^' cut). Adds vibrato on held notes."""
    tokens = " ".join(bars).split()
    assert len(tokens) == 16 * len(bars), "each melody bar needs 16 tokens"
    starts = [i for i, t in enumerate(tokens) if t not in (".",)] + [len(tokens)]
    for i, tok in enumerate(tokens):
        if tok == "^":
            p.set(i, LEAD, "^^^")
        elif tok != ".":
            p.set(i, LEAD, LEAD_V.note(tok), LEAD_V.sample)
    for a, b in zip(starts, starts[1:]):
        if tokens[a] != "^" and b - a >= 4:
            for r in range(a + 2, b):
                p.set_effect(r, LEAD, fx.vibrato(6, 3))


def snare_roll(p, start_row):
    """16-row build: 8ths, then 16ths getting louder, then retriggered 32nds."""
    for k, r in enumerate(range(start_row, start_row + 8, 2)):
        hit(p, r, DRUMS, "snare", volume=24 + k * 6)
    for k, r in enumerate(range(start_row + 8, start_row + 12)):
        hit(p, r, DRUMS, "snare", volume=44 + k * 5)
    for r in range(start_row + 12, start_row + 16):
        hit(p, r, DRUMS, "snare", effect=fx.retrig(3))


# --- Patterns ---------------------------------------------------------------------------------------
# 0: intro - stab hits with zaps, then a whoosh and snare-roll build
intro = song.patterns[0]
for row, chord in [(0, "Em"), (6, "Em"), (12, "Em"), (16, "C"), (22, "D"), (28, "B"), (32, "Em")]:
    stab(intro, row, chord)
    hit(intro, row, DRUMS, "kick")
    _, _, root, _ = CHORD[chord]
    intro.set(row, BASS, BASS_V.note(root), BASS_V.sample)
hit(intro, 0, PERC, "crash")
for row, note in [(8, "C-6"), (24, "D-6"), (36, "E-6"), (40, "G-6")]:
    hit(intro, row, PERC, "zap", note=note)
hit(intro, 48, PERC, "whoosh")
for k, row in enumerate(range(36, 64, 2)):
    intro.set(row, BASS, BASS_V.note("E-3"), BASS_V.sample, volume=min(64, 20 + k * 3))
snare_roll(intro, 48)

# 1: groove - break, hats, acid bass; big stabs on the downbeats
groove = song.add_pattern(64, name="groove")
beat(groove)
bassline(groove, ["Em", "Em", "C", "D"])
stab(groove, 0, "Em")
stab(groove, 32, "C")
hit(groove, 0, PERC, "crash")

# 2: groove + stab riff
groove2 = song.add_pattern(64, name="groove + stabs")
beat(groove2)
bassline(groove2, ["Em", "Em", "C", "D"])
stabs(groove2, ["Em", "Em", "C", "D"])
hit(groove2, 0, PERC, "crash")

# 3: theme A - the lead takes over channel 4
theme_a = song.add_pattern(64, name="theme A")
beat(theme_a, fill=False)
bassline(theme_a, ["Em", "Em", "C", "D"])
melody(theme_a, [
    "E-6 . . . D-6 . E-6 . G-6 . . . F#6 . E-6 .",
    "D-6 . . . B-5 . . . ^ . . . B-5 . D-6 .",
    "E-6 . . . G-6 . . . A-6 . G-6 . E-6 . . .",
    "F#6 . . . . . . . D-6 . E-6 . F#6 . A-6 .",
])
hit(theme_a, 0, PERC, "crash")

# 4: theme B - climbs, ends on the B major turnaround with a fill
theme_b = song.add_pattern(64, name="theme B")
beat(theme_b)
bassline(theme_b, ["Em", "Em", "C", "B"])
melody(theme_b, [
    "B-6 . . . . . A-6 . G-6 . . . F#6 . E-6 .",
    "G-6 . F#6 . E-6 . . . ^ . . . E-6 . G-6 .",
    "G-6 . . . E-6 . . . G-6 . A-6 . G-6 . E-6 .",
    "D#6 . . . . . . . F#6 . . . B-5 . . .",
])

# 5: breakdown - half-time bass, arpeggiated lead chords, zaps, then whoosh + roll back in
breakdown = song.add_pattern(64, name="breakdown")
hit(breakdown, 0, DRUMS, "kick")
hit(breakdown, 0, PERC, "crash")
hit(breakdown, 16, DRUMS, "kick")
for bar, (chord, arp) in enumerate([("Am", fx.chord("min")), ("Em", fx.chord("min")), ("C", fx.chord("maj")), ("B", fx.chord("maj"))]):
    root, _, bass_root, _ = CHORD[chord]
    for half in range(2):
        breakdown.set(bar * 16 + half * 8, BASS, BASS_V.note(bass_root), BASS_V.sample)
    lead_root = notes.name(notes.transpose(root, 12 if chord != "Em" else 0))
    breakdown.set(bar * 16, LEAD, LEAD_V.note(lead_root), LEAD_V.sample, effect=arp)
    for r in range(1, 16):
        breakdown.set_effect(bar * 16 + r, LEAD, arp)  # ProTracker arpeggio must repeat on every row
for row, note in [(20, "E-6"), (28, "B-5"), (36, "G-6")]:
    hit(breakdown, row, PERC, "zap", note=note)
hit(breakdown, 48, PERC, "whoosh")
for row in range(32, 48, 4):
    hit(breakdown, row, DRUMS, "kick")
snare_roll(breakdown, 48)

# 6: final theme B, which loops back to the first groove
theme_b_end = song.duplicate_pattern(theme_b)
theme_b_end.name = "theme B (loop)"
theme_b_end.set_effect(63, PERC, fx.position_jump(1))

song.order = [intro.index, groove.index, groove2.index, theme_a.index, theme_b.index,
              groove2.index, breakdown.index, theme_a.index, theme_b_end.index]

# Sanity: every note must be playable by ProTracker.
for pat in song.patterns:
    for row, ch, cell in pat.cells():
        assert cell.note == 0 or PT_LOW <= cell.note <= PT_HIGH, (pat.index, row, ch, cell)

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    song.save(os.path.join(OUT, "arena_anthem.mod"))
    report = song.render(os.path.join(OUT, "arena_anthem.wav"), amiga="a500")
    print(f"one pass: {song.duration:.1f}s; loop restarts at the first groove")
    print(report)
