"""gameboy_korobeiniki.py - Nintendo Game Boy (DMG) arrangement of "Korobeiniki".

Chip:   Game Boy APU (2 pulse channels with 12.5/25/50/75% duty, a 4-bit 32-step wave
        channel, an LFSR noise channel; hard left/centre/right panning only).
        Recreated with synthesized samples played through OpenMPT's mixer (nearest-neighbour
        resampling keeps the 4-bit steps crisp).
Format: IT, 4 channels.
Tune:   "Korobeiniki", a 19th-century Russian folk song (public domain) - the melody made famous
        by Tetris (1989). This arrangement (bass, harmony, drums, bridge) is original; like the
        game it speeds up: the reprise and every later loop run at tempo 165.

Run:  python -m mptscript run examples/chipsets/gameboy_korobeiniki.py --play
"""

import os

import mptscript as mpt
from mptscript import chip, fx
from mptscript.compose import line

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MPTSCRIPT_OUT", HERE)

song = mpt.Song.new("it", channels=4, title="Korobeiniki (DMG)", artist="trad. / mptscript", tempo=150, speed=6)
song.rows_per_beat, song.rows_per_measure = 4, 16
song.sample_preamp = 44

# --- The four DMG voices ----------------------------------------------------------------
pulse1 = song.add_instrument("Pulse 25%", chip.pulse(0.25), volume=46, envelope=chip.adsr(0, 8, 40, 6))
pulse2 = song.add_instrument("Pulse 12.5%", chip.pulse(0.125), volume=30, envelope=chip.adsr(0, 12, 26, 6))
# A classic Game Boy bass wavetable: half-sine-ish ramp (32 x 4-bit samples).
GB_WAVE = [0, 2, 4, 6, 8, 10, 12, 13, 14, 15, 15, 15, 14, 14, 13, 12, 10, 8, 6, 4, 3, 2, 1, 1, 0, 0, 1, 1, 2, 2, 1, 0]
wave = song.add_instrument("Wave bass", chip.wavetable(GB_WAVE, bits=4, amplitude=0.8), volume=58)
noise_long = chip.noise(periodic=False)
snare = song.add_instrument("Noise snare", noise_long, volume=34, envelope=chip.envelope([(0, 64), (2, 40), (9, 0)]))
hat = song.add_instrument("Noise hat", chip.noise(periodic=True), volume=16, envelope=chip.envelope([(0, 64), (2, 0)]))
kick = song.add_instrument("Noise kick", noise_long, volume=40, envelope=chip.envelope([(0, 64), (3, 0)]))

LEAD, HARM, BASS, NOISE = range(4)
# DMG panning is all-or-nothing per channel: centre, left, centre, right.
for ch, (name, pan) in enumerate([("Pulse 1", 128), ("Pulse 2", 0), ("Wave", 128), ("Noise", 256)]):
    song.channels[ch].update(name=name, pan=pan)

Q, E, H, DQ = 1, 0.5, 2, 1.5  # quarter, eighth, half, dotted quarter (in beats)

# Korobeiniki (traditional), OpenMPT octaves: C-5 = middle C.
THEME_1 = [("E-6", Q), ("B-5", E), ("C-6", E), ("D-6", Q), ("C-6", E), ("B-5", E),
           ("A-5", Q), ("A-5", E), ("C-6", E), ("E-6", Q), ("D-6", E), ("C-6", E),
           ("B-5", DQ), ("C-6", E), ("D-6", Q), ("E-6", Q),
           ("C-6", Q), ("A-5", Q), ("A-5", Q), ("r", Q)]
THEME_2 = [("r", E), ("D-6", Q), ("F-6", E), ("A-6", Q), ("G-6", E), ("F-6", E),
           ("E-6", DQ), ("C-6", E), ("E-6", Q), ("D-6", E), ("C-6", E),
           ("B-5", Q), ("B-5", E), ("C-6", E), ("D-6", Q), ("E-6", Q),
           ("C-6", Q), ("A-5", Q), ("A-5", Q), ("r", Q)]
CHORDS_1 = ["Am", "Am", "E", "Am"]  # one chord per bar (the folk tune's harmony)
CHORDS_2 = ["Dm", "C", "E", "Am"]
ROOTS = {"Am": ("A-3", 3), "E": ("E-3", 4), "Dm": ("D-3", 3), "C": ("C-3", 4), "G": ("G-3", 4), "F": ("F-3", 4)}


def bass(p, chords, start_bar=0):
    """Octave-bouncing eighths on the wave channel."""
    for bar, chord in enumerate(chords):
        root, _ = ROOTS[chord]
        tokens = []
        for i in range(8):
            n = mpt.notes.transpose(root, 12 if i % 2 else 0)
            tokens.append(mpt.notes.name(n))
            tokens.append(".")
        p.write(BASS, " ".join(tokens), instrument=wave, start=(start_bar + bar) * 16)


def harmony(p, chords, start_bar=0):
    """Pulse 2: off-beat chord jabs (third + fifth alternating), a staple of handheld arrangements."""
    for bar, chord in enumerate(chords):
        root, third = ROOTS[chord]
        r5 = mpt.notes.transpose(root, 24)
        for k, row in enumerate(range(2, 16, 4)):
            n = mpt.notes.transpose(r5, third if k % 2 == 0 else 7)
            p.set((start_bar + bar) * 16 + row, HARM, n, pulse2)
            p.set((start_bar + bar) * 16 + row + 1, HARM, "===")


def drums(p, bars, start_bar=0, fill=False):
    for bar in range(bars):
        base = (start_bar + bar) * 16
        steps = "k.h.s.h.k.k.s.hh" if not (fill and bar == bars - 1) else "k.h.s.h.k.s.sss."
        for i, c in enumerate(steps):
            if c == "k":
                p.set(base + i, NOISE, "C-4", kick)
            elif c == "s":
                p.set(base + i, NOISE, "G-5", snare)
            elif c == "h":
                p.set(base + i, NOISE, "C-7", hat)


def theme_pattern(name, melody, chords, transpose=0, fill=False):
    p = song.add_pattern(64, name=name)
    items = [(n if n == "r" else mpt.notes.name(mpt.notes.transpose(n, transpose)), b) for n, b in melody]
    line(p, LEAD, items, pulse1, rows_per_beat=4, gap=1)
    bass(p, chords)
    harmony(p, chords)
    drums(p, 4, fill=fill)
    return p


# --- Patterns ------------------------------------------------------------------------------
intro = song.patterns[0]
intro.rows = 32
intro.name = "intro"
intro.set(0, NOISE, "C-4", kick, effect=fx.set_tempo(150))  # reset the tempo every loop
bass(intro, ["Am", "E"])
drums(intro, 2, fill=True)

a1 = theme_pattern("A1", THEME_1, CHORDS_1)
a2 = theme_pattern("A2", THEME_2, CHORDS_2, fill=True)

# Original bridge: lead holds long notes over a descending line, harmony arpeggiates (Jxy).
bridge = song.add_pattern(64, name="bridge")
BRIDGE = [("A-5", 2), ("C-6", 1), ("E-6", 1), ("D-6", 3), ("B-5", 1), ("C-6", 2), ("A-5", 2), ("B-5", 2), ("G#5", 2)]
line(bridge, LEAD, BRIDGE, pulse1, rows_per_beat=4)
for bar, (chord, arp) in enumerate([("Am", fx.chord("min")), ("G", fx.chord("maj")), ("F", fx.chord("maj")), ("E", fx.chord("maj"))]):
    root, _ = ROOTS[chord]
    bridge.set(bar * 16, HARM, mpt.notes.transpose(root, 24), pulse2, effect=arp)
    for r in range(1, 16):
        bridge.set_effect(bar * 16 + r, HARM, arp)
bass(bridge, ["Am", "G", "F", "E"])
drums(bridge, 4, fill=True)

a3 = theme_pattern("A1 reprise", THEME_1, CHORDS_1)
a4 = theme_pattern("A2 (faster)", THEME_2, CHORDS_2, fill=True)
a4.set_effect(63, BASS, fx.position_jump(1))  # loop back to A1...
a3.set_effect(0, BASS, fx.set_tempo(165))     # ...and like the game, the reprise is faster

song.order = [intro.index, a1.index, a2.index, bridge.index, a3.index, a4.index]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    song.save(os.path.join(OUT, "gameboy_korobeiniki.it"))
    print(song.render(os.path.join(OUT, "gameboy_korobeiniki.wav"), interpolation="nearest"))
