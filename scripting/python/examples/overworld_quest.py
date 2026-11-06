"""overworld_quest.py - an original heroic NES-style adventure march that loops.

Written in the spirit of 8-bit overworld themes: B-flat major with a
mixolydian flat-seven chord, dotted rhythms, triplet fanfares and a driving
march beat. It uses the NES's four voices:

  ch0  Pulse 1   50% duty lead (auto-vibrato on long notes)
  ch1  Pulse 2   25% duty harmony
  ch2  Triangle  staccato march bass
  ch3  Noise     snare / hat / thump

Timing: tempo 150, speed 2, 12 rows per beat (one bar = 48 rows), which allows
16ths (3 rows), triplet 8ths (4 rows), 8ths (6 rows) and dotted 8ths (9 rows).

Form: intro (2 bars) | A (8 bars) | A' (8 bars) | B (8 bars), then a jump back to A.

Run:  python -m mptscript run examples/overworld_quest.py --play
"""

import os
from fractions import Fraction as F

import mptscript as mpt
from mptscript import chip, fx, notes

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MPTSCRIPT_OUT", HERE)  # songs are written next to this script

ROWS_PER_BEAT = 12
BAR = 4 * ROWS_PER_BEAT
T = F(1, 3)  # triplet eighth, in beats

song = mpt.Song.new("it", channels=4, title="Overworld Quest", artist="mptscript", tempo=150, speed=2)
song.rows_per_beat, song.rows_per_measure = ROWS_PER_BEAT, BAR
song.sample_preamp = 44

# --- Instruments: the four NES voices -------------------------------------------
lead = song.add_instrument("Pulse 50% lead", chip.pulse(0.5), volume=42,
                           envelope=chip.adsr(attack=0, decay=14, sustain=38, release=6),
                           vibrato=(10, 3, 60))  # (rate, depth, sweep): vibrato fades in on held notes
harm = song.add_instrument("Pulse 25% harmony", chip.pulse(0.25), volume=26,
                           envelope=chip.adsr(attack=0, decay=20, sustain=20, release=6))
tri = song.add_instrument("Triangle bass", chip.triangle(), volume=60)
noise = chip.noise()
snare = song.add_instrument("Noise snare", noise, volume=34, envelope=chip.envelope([(0, 64), (3, 34), (12, 0)]))
hat = song.add_instrument("Noise hat", noise, volume=14, envelope=chip.envelope([(0, 64), (2, 0)]))
thump = song.add_instrument("Noise thump", noise, volume=30, envelope=chip.envelope([(0, 64), (4, 0)]))

LEAD, HARM, BASS, DRUMS = range(4)
for ch, (name, pan) in enumerate([("Pulse 1", 112), ("Pulse 2", 150), ("Triangle", 128), ("Noise", 128)]):
    song.channels[ch].update(name=name, pan=pan)


# --- Writing helpers ---------------------------------------------------------------
def rows(beats) -> int:
    r = F(beats) * ROWS_PER_BEAT
    assert r.denominator == 1, f"{beats} beats is not on the {ROWS_PER_BEAT}-rows-per-beat grid"
    return int(r)


def line(pat, ch, items, instrument, start=0):
    """items: (note, beats) pairs; note 'r' is a rest (sends note-off). Returns end row."""
    row = start
    for note, beats in items:
        if note == "r":
            pat.set(row, ch, "===")
        else:
            pat.set(row, ch, note, instrument)
        row += rows(beats)
    return row


def bars_check(items, bars):
    total = sum(F(b) for _, b in items)
    assert total == 4 * bars, f"phrase is {total} beats, expected {4 * bars}"
    return items


CHORDS = {  # bar chord -> (root, intervals)
    "Bb": ("Bb", (0, 4, 7)), "Ab": ("Ab", (0, 4, 7)), "Eb": ("Eb", (0, 4, 7)), "F": ("F-", (0, 4, 7)),
    "F7": ("F-", (0, 4, 10)), "Gm": ("G-", (0, 3, 7)), "Cm": ("C-", (0, 3, 7)), "Ebm": ("Eb", (0, 3, 7)),
}


def chord_note(chord, degree, octave):
    root, iv = CHORDS[chord]
    base = notes.parse(f"{root}{octave}")
    return notes.name(base + iv[degree])


def harmony(pat, chords, rhythm=((F(3, 2), 1), (F(1, 2), 2), (1, 1), (1, 2))):
    """Pulse 2: chord thirds/fifths (or sevenths) in a march rhythm, one chord per bar."""
    for bar, chord in enumerate(chords):
        row = bar * BAR
        for beats, degree in rhythm:
            pat.set(row, HARM, chord_note(chord, degree, 5), harm)
            row += rows(beats)


def bass(pat, chords):
    """Triangle: oom-pah eighths (root, octave, fifth, octave) with staccato cuts."""
    for bar, chord in enumerate(chords):
        root, iv = CHORDS[chord]
        r = notes.parse(f"{root}3")
        figure = [r, r + 12, r + iv[2], r + 12] * 2
        for i, n in enumerate(figure):
            row = bar * BAR + i * rows(F(1, 2))
            pat.set(row, BASS, n, tri)
            pat.set(row + 4, BASS, "^^^")  # triangle has no volume control: cut for staccato


DRUM_BAR = "k.h.s.hhk.h.s.hs"  # 16ths: k thump, h hat, s snare, S accent, . rest
DRUM_FILL = "s.s.sss.SsSsSSSS"


def drums(pat, n_bars, fill_last=False):
    for bar in range(n_bars):
        steps = DRUM_FILL if fill_last and bar == n_bars - 1 else DRUM_BAR
        for i, s in enumerate(steps):
            row = bar * BAR + i * rows(F(1, 4))
            if s == "k":
                pat.set(row, DRUMS, "C-4", thump)
            elif s == "h":
                pat.set(row, DRUMS, "C-8", hat)
            elif s in "sS":
                pat.set(row, DRUMS, "G-5", snare, volume=48 if s == "S" else None)


# --- Melodies (OpenMPT octaves: C-5 is middle C) -----------------------------------------
INTRO = bars_check([
    ("Bb5", T), ("Bb5", T), ("Bb5", T), ("D-6", 1), ("F-6", 1), ("r", 1),
    ("Ab5", T), ("Ab5", T), ("Ab5", T), ("C-6", 1), ("Eb6", 1), ("F-6", 1),
], 2)

A_FIRST = bars_check([  # Bb | Bb | Ab | Bb
    ("F-5", F(3, 4)), ("Bb5", F(1, 4)), ("D-6", 1), ("C-6", F(1, 2)), ("Bb5", F(1, 2)), ("F-6", 1),
    ("Eb6", T), ("D-6", T), ("C-6", T), ("D-6", 2), ("r", 1),
    ("C-6", F(3, 4)), ("Ab5", F(1, 4)), ("C-6", F(1, 2)), ("Eb6", F(1, 2)), ("Ab6", F(3, 2)), ("G-6", F(1, 2)),
    ("F-6", F(3, 2)), ("D-6", F(1, 2)), ("Bb5", 1), ("r", 1),
], 4)

A_SECOND = bars_check([  # Eb | Cm F | Gm | F7  (half cadence)
    ("G-5", F(3, 4)), ("Bb5", F(1, 4)), ("Eb6", 1), ("D-6", F(1, 2)), ("Eb6", F(1, 2)), ("G-6", 1),
    ("F-6", T), ("Eb6", T), ("D-6", T), ("C-6", 1), ("Eb6", F(1, 2)), ("D-6", F(1, 2)), ("C-6", 1),
    ("D-6", F(3, 4)), ("Bb5", F(1, 4)), ("G-5", 1), ("Bb5", F(1, 2)), ("D-6", F(1, 2)), ("G-6", 1),
    ("F-6", 2), ("A-5", T), ("C-6", T), ("Eb6", T), ("F-6", 1),
], 4)

A2_SECOND = bars_check([  # Eb | Ebm | Bb/F F7 | Bb  (full cadence)
    ("G-5", F(3, 4)), ("Bb5", F(1, 4)), ("Eb6", 1), ("G-6", 1), ("Bb6", 1),
    ("Bb6", F(3, 2)), ("Gb6", F(1, 2)), ("Eb6", 1), ("Db6", 1),
    ("D-6", T), ("Eb6", T), ("F-6", T), ("Bb6", 1), ("A-6", 1), ("C-7", 1),
    ("Bb6", 2), ("F-6", F(1, 2)), ("D-6", F(1, 2)), ("Bb5", 1),
], 4)

B_FIRST = bars_check([  # Gm | Eb | Bb | F
    ("D-6", F(3, 2)), ("G-6", F(1, 2)), ("Bb6", 1), ("A-6", F(1, 2)), ("G-6", F(1, 2)),
    ("G-6", F(3, 2)), ("Eb6", F(1, 2)), ("Bb5", 2),
    ("D-6", F(3, 4)), ("F-6", F(1, 4)), ("Bb6", 1), ("A-6", F(1, 2)), ("Bb6", F(1, 2)), ("C-7", 1),
    ("A-6", 2), ("F-6", T), ("G-6", T), ("A-6", T), ("C-7", 1),
], 4)

B_SECOND = bars_check([  # Gm | Eb | Cm | F (fanfare, then loop to A)
    ("Bb6", F(3, 2)), ("A-6", F(1, 2)), ("G-6", 1), ("D-6", 1),
    ("Eb6", T), ("F-6", T), ("G-6", T), ("Bb6", 1), ("G-6", 1), ("Eb6", 1),
    ("C-6", F(3, 4)), ("Eb6", F(1, 4)), ("G-6", 1), ("F-6", F(1, 2)), ("Eb6", F(1, 2)), ("D-6", F(1, 2)), ("C-6", F(1, 2)),
    ("F-5", T), ("F-5", T), ("F-5", T), ("A-5", T), ("C-6", T), ("Eb6", T), ("F-6", F(3, 2)), ("r", F(1, 2)),
], 4)


# --- Patterns ----------------------------------------------------------------------------
def section(name, melody, chords, fill=False, pattern=None):
    p = pattern or song.add_pattern(BAR * len(chords))
    if pattern is not None:
        p.rows = BAR * len(chords)
    p.name = name
    line(p, LEAD, melody, lead)
    harmony(p, chords)
    bass(p, chords)
    drums(p, len(chords), fill_last=fill)
    return p


intro = song.patterns[0]
intro.rows = 2 * BAR
intro.name = "intro"
line(intro, LEAD, INTRO, lead)
# Harmony doubles the fanfare a third below; bass and thump hit the chord changes.
line(intro, HARM, [("D-5", T), ("D-5", T), ("D-5", T), ("F-5", 1), ("Bb5", 1), ("r", 1),
                   ("C-5", T), ("C-5", T), ("C-5", T), ("Eb5", 1), ("Ab5", 1), ("A-5", 1)], harm)
for bar, root in enumerate(["Bb3", "Ab3"]):
    for beat in range(4):
        intro.set(bar * BAR + beat * ROWS_PER_BEAT, BASS, root if beat < 2 else notes.transpose(root, 12), tri)
        intro.set(bar * BAR + beat * ROWS_PER_BEAT + 8, BASS, "^^^")
drums(intro, 2, fill_last=True)

a1 = section("A1", A_FIRST, ["Bb", "Bb", "Ab", "Bb"])
a2 = section("A2", A_SECOND, ["Eb", "Cm", "Gm", "F7"])
a3 = section("A'2", A2_SECOND, ["Eb", "Ebm", "F7", "Bb"])
b1 = section("B1", B_FIRST, ["Gm", "Eb", "Bb", "F"])
b2 = section("B2", B_SECOND, ["Gm", "Eb", "Cm", "F7"], fill=True)

# Order: intro plays once, then A A' B loops forever (B2 ends with a jump to order 1).
song.order = [intro.index, a1.index, a2.index, a1.index, a3.index, b1.index, b2.index]
b2.set_effect(b2.rows - 1, BASS, fx.position_jump(1))

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    song.save(os.path.join(OUT, "overworld_quest.it"))
    report = song.render(os.path.join(OUT, "overworld_quest.wav"))
    print(f"one pass: {song.duration:.1f}s (intro + loop)")
    print(report)
