"""opl3_dos_shooter.py - Yamaha OPL3 (Sound Blaster) FM metal, in the style of early-90s DOS shooters (Doom era).

Chip:   Yamaha YMF262 OPL3, emulated by OpenMPT's Opal core (real FM synthesis, no samples).
Format: MPTM (OpenMPT's IT extension; the format that stores OPL3 instruments with all 8 waveforms).
Style:  E-minor palm-muted riffing, double-tracked FM "distortion guitars" (root + fifth),
        FM bass, an overdriven FM lead with vibrato and slides, and FM drum patches -
        the sound of a General MIDI score played through an AdLib-compatible card.
Tune:   original.

Run:  python -m mptscript run examples/chipsets/opl3_dos_shooter.py --play
"""

import os

import mptscript as mpt
from mptscript import fx, notes, opl
from mptscript.opl import Op

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MPTSCRIPT_OUT", HERE)

song = mpt.Song.new("mptm", channels=8, title="Hellgate Breach", artist="mptscript", tempo=140, speed=6)
song.sample_preamp = 40

# --- OPL3 instruments --------------------------------------------------------------------------
guitar = song.add_opl_instrument("FM Dist Guitar", opl.PRESETS["dist_guitar"], volume=50)
guitar5 = song.add_opl_instrument("FM Dist Guitar (5th)", opl.PRESETS["dist_guitar"], volume=40)
bass = song.add_opl_instrument("FM Bass", opl.PRESETS["bass"], volume=56)
lead = song.add_opl_instrument("FM Overdrive Lead", opl.patch(
    Op(mult=2, level=14, attack=15, decay=1, sustain_level=2, release=6, wave=1),
    Op(mult=1, level=0, attack=15, decay=0, sustain_level=1, release=5, wave=6, vibrato=True), feedback=6), volume=44)
kick = song.add_opl_instrument("FM Kick", opl.PRESETS["kick"], volume=64)
snare = song.add_opl_instrument("FM Snare", opl.PRESETS["snare"], volume=54)
hat = song.add_opl_instrument("FM Hihat", opl.PRESETS["hihat"], volume=30)
pad = song.add_opl_instrument("FM Strings", opl.PRESETS["strings"], volume=30)

GTR, GTR5, BASS, LEAD, KICK, SNARE, HAT, PAD = range(8)
for ch, (name, pan) in enumerate([("Guitar L", 64), ("Guitar R 5th", 192), ("Bass", 128), ("Lead", 128),
                                  ("Kick", 128), ("Snare", 128), ("Hat", 160), ("Strings", 96)]):
    song.channels[ch].update(name=name, pan=pan)


# --- Riff writing ---------------------------------------------------------------------------------
def riff(p, steps, start_bar=0, bars=None):
    """steps: 16th-note tokens per bar. Lowercase 'e' = palm-muted chug on low E,
    a note name = power chord on that root (guitar + fifth + bass), '.' = let ring, '-' = mute."""
    tokens = steps.split()
    for i, tok in enumerate(tokens):
        row = start_bar * 16 + i
        if tok == ".":
            continue
        if tok == "-":
            for ch in (GTR, GTR5):
                p.set(row, ch, "^^^")
            continue
        root = "E-3" if tok == "e" else tok
        n = notes.parse(root)
        p.set(row, GTR, n, guitar, volume=40 if tok == "e" else 52)
        p.set(row, GTR5, n + 7, guitar5, volume=30 if tok == "e" else 42)
        p.set(row, BASS, n - 12, bass)
        if tok == "e":  # palm mute: cut after one 16th
            for ch in (GTR, GTR5):
                p.set(row + 1, ch, "^^^")


RIFF_A = [
    "e e G-3 . e e A-3 . e e Bb3 . A-3 . G-3 -",
    "e e D-4 . e e C-4 . e e B-3 . G-3 . A-3 -",
    "e e G-3 . e e A-3 . e e Bb3 . A-3 . G-3 -",
    "e e D-4 . C-4 . B-3 . G-3 . F#3 . D-3 . . -",
]
RIFF_B = [
    "A-3 . . e e e C-4 . . e e e B-3 . G-3 -",
    "A-3 . . e e e D-4 . . e e e C-4 . B-3 -",
    "F-3 . . e e e G-3 . . e e e A-3 . Bb3 -",
    "B-3 . . . . . . . B-3 . A#3 . A-3 . G#3 -",
]


def drums(p, bars=4, start_bar=0, fill=True, half_time=False):
    kick_pat = "x.x...x.xx....x." if not half_time else "x.......x.x....."
    snare_pat = "....x.......x..." if not half_time else "........x......."
    hat_pat = "x.x.x.x.x.x.x.x."
    for bar in range(start_bar, start_bar + bars):
        last = fill and bar == start_bar + bars - 1
        for i in range(16):
            row = bar * 16 + i
            if last and i >= 12:
                p.set(row, SNARE, "G-5", snare, volume=40 + (i - 12) * 6)
                continue
            if kick_pat[i] == "x":
                p.set(row, KICK, "C-4", kick)
            if snare_pat[i] == "x":
                p.set(row, SNARE, "G-5", snare)
            if hat_pat[i] == "x":
                p.set(row, HAT, "C-7", hat, volume=36 if i % 4 == 0 else 24)


def strings(p, chords):
    for bar, chord in enumerate(chords):
        p.set(bar * 16, PAD, chord, pad)
    p.set(len(chords) * 16 - 1, PAD, "===")


# --- Patterns ---------------------------------------------------------------------------------------
intro = song.patterns[0]
intro.name = "intro"
for bar in range(4):
    riff(intro, RIFF_A[bar], start_bar=bar)
drums(intro, bars=2, start_bar=2)
intro.set(0, KICK, "C-4", kick)
intro.set(0, PAD, "E-5", pad)
intro.set(31, PAD, "===")

verse = song.add_pattern(64, name="riff A")
for bar in range(4):
    riff(verse, RIFF_A[bar], start_bar=bar)
drums(verse)

bridge = song.add_pattern(64, name="riff B")
for bar in range(4):
    riff(bridge, RIFF_B[bar], start_bar=bar)
drums(bridge)
strings(bridge, ["A-5", "D-5", "F-5", "B-4"])

solo = song.add_pattern(64, name="solo")
for bar in range(4):
    riff(solo, RIFF_A[bar], start_bar=bar)
drums(solo)
SOLO = ("B-5 . . . E-6 . . . G-6 . F#6 . E-6 . D-6 . "
        "E-6 . . . . . . . B-5 . D-6 . E-6 . G-6 . "
        "A-6 . . . G-6 . F#6 . G-6 . . . E-6 . . . "
        "B-6 . . . . . . . A-6 . G-6 . F#6 . D-6 .")
solo.write(LEAD, SOLO, instrument=lead)
for row in (1, 17, 41, 49):
    solo.set_effect(row, LEAD, fx.vibrato(6, 4))
solo.set(32, LEAD, "A-6", lead, effect=fx.tone_porta(0x20))  # slide up into the high phrase
solo.set(63, LEAD, "===")

breakdown = song.add_pattern(64, name="breakdown")
for bar in range(4):
    for i in range(0, 16, 2):
        row = bar * 16 + i
        breakdown.set(row, GTR, "E-3", guitar, volume=46)
        breakdown.set(row, GTR5, "B-3", guitar5, volume=34)
        breakdown.set(row + 1, GTR, "^^^")
        breakdown.set(row + 1, GTR5, "^^^")
    breakdown.set(bar * 16, BASS, "E-2", bass)
drums(breakdown, half_time=True)
for i, n in enumerate(["C-5", "A-4", "F-4", "D-4"]):  # tom-style FM fill using the kick patch, pitched
    breakdown.set(60 + i, KICK, n, kick)
strings(breakdown, ["E-5", "C-5", "D-5", "B-4"])

ending = song.duplicate_pattern(verse)
ending.name = "riff A (loop)"
ending.set_effect(63, PAD, fx.position_jump(1))

song.order = [intro.index, verse.index, verse.index, bridge.index, solo.index, bridge.index,
              breakdown.index, ending.index]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    song.save(os.path.join(OUT, "opl3_dos_shooter.mptm"))
    print(song.render(os.path.join(OUT, "opl3_dos_shooter.wav")))
