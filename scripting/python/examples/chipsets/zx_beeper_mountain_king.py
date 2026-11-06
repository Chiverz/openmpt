"""zx_beeper_mountain_king.py - ZX Spectrum 48K beeper: "In the Hall of the Mountain King".

Chip:   the Spectrum 48K's "beeper": the ULA toggles a single speaker bit, so there is exactly one
        1-bit square-wave voice with no volume control. Recreated with a full-scale 50% square,
        one channel, nearest-neighbour resampling and no envelopes.
Format: IT, 1 channel.
Tune:   Edvard Grieg, "In the Hall of the Mountain King" (1875, public domain) - the tune
        Manic Miner (1983) made the sound of the Spectrum. Like Grieg's original it climbs in
        register and speeds up on every repeat, then loops.

Run:  python -m mptscript run examples/chipsets/zx_beeper_mountain_king.py --play
"""

import os

import mptscript as mpt
from mptscript import chip, fx, notes
from mptscript.compose import line

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MPTSCRIPT_OUT", HERE)

song = mpt.Song.new("it", channels=1, title="Mountain King (beeper)", artist="E. Grieg / mptscript", tempo=110, speed=6)
song.sample_preamp = 32
beep = song.add_instrument("1-bit beeper", chip.square(amplitude=1.0), volume=64)  # 1 bit: on or off
song.channels[0].update(name="Beeper", pan=128)

E8, Q, H = 0.5, 1, 2
# Grieg's theme in B minor (OpenMPT octaves: B-4 is the B below middle C).
THEME = [("B-4", E8), ("C#5", E8), ("D-5", E8), ("E-5", E8), ("F#5", E8), ("D-5", E8), ("F#5", Q),
         ("F-5", E8), ("C#5", E8), ("F-5", Q), ("E-5", E8), ("C-5", E8), ("E-5", Q),
         ("B-4", E8), ("C#5", E8), ("D-5", E8), ("E-5", E8), ("F#5", E8), ("D-5", E8), ("F#5", E8), ("B-5", E8),
         ("A-5", E8), ("F#5", E8), ("D-5", E8), ("F#5", E8), ("A-5", H)]

# (tempo, octave shift) for each repeat: up the register and faster, as in the orchestral score.
REPEATS = [(110, 0), (125, 0), (145, 12), (170, 12), (200, 24)]

patterns = []
for i, (tempo, shift) in enumerate(REPEATS):
    p = song.patterns[0] if i == 0 else song.add_pattern(64)
    p.name = f"theme x{i + 1} ({tempo})"
    items = [(notes.name(notes.transpose(n, shift)), b) for n, b in THEME]
    line(p, 0, items, beep, rows_per_beat=4, gap=1)  # staccato: the beeper loop cuts every note short
    p.set_effect(0, 0, fx.set_tempo(tempo))
    patterns.append(p)

# Finale: a hammered B with a fake chord (the beeper can only fake harmony with a fast arpeggio).
finale = song.add_pattern(32, name="finale")
finale.set(0, 0, "B-6", beep, effect=fx.arpeggio(3, 7))
for r in range(1, 24):
    finale.set_effect(r, 0, fx.arpeggio(3, 7))
for r in (24, 26, 28):
    finale.set(r, 0, "B-4", beep)
    finale.set(r + 1, 0, "^^^")
finale.set(30, 0, "B-3", beep)
finale.set_effect(31, 0, fx.position_jump(0))

song.order = [p.index for p in patterns] + [finale.index]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    song.save(os.path.join(OUT, "zx_beeper_mountain_king.it"))
    print(song.render(os.path.join(OUT, "zx_beeper_mountain_king.wav"), interpolation="nearest", stereo_separation=0))
