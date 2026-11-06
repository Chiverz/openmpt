"""ym2612_genesis_speed.py - Sega Mega Drive / Genesis "speed platformer" first-stage theme,
in the style of early-90s Sega mascot games.

Chips:  Yamaha YM2612 (6 x 4-operator FM; channel 6 doubles as an 8-bit DAC for drum samples)
        + TI SN76489 PSG (3 square channels + noise).
        FM voices are rendered by mptscript.chip.fm(), a 4-operator FM synth with the YM2612's
        eight operator algorithms; each tone loops its steady-state tail so held notes keep their
        timbre. PSG and DAC parts use squares, LFSR noise and 8-bit, 8 kHz drum samples.
Format: IT, 8 channels (5 FM + DAC + 2 PSG).
Tune:   original. D major, 150 BPM, syncopated.

Run:  python -m mptscript run examples/chipsets/ym2612_genesis_speed.py --play
"""

import os

import mptscript as mpt
from mptscript import chip, fx, notes
from mptscript.chip import FMOp

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MPTSCRIPT_OUT", HERE)

song = mpt.Song.new("it", channels=8, title="Palm Shore Dash (YM2612)", artist="mptscript", tempo=150, speed=6)
song.sample_preamp = 36

# --- FM patches (algorithm, operators: ratio, level, attack s, decay s, sustain) -------------
slap_bass = chip.fm([FMOp(1, 1.6, decay=0.06, sustain=0.15), FMOp(1, 1.0, decay=0.5, sustain=0.5),
                     FMOp(3, 0.6, decay=0.04, sustain=0.0), FMOp(1, 0.7, decay=0.3, sustain=0.4)],
                    algorithm=4, feedback=0.4, root="C-4", duration=0.9, name="FM slap bass")
epiano = chip.fm([FMOp(14, 0.5, decay=0.05, sustain=0.0), FMOp(1, 1.0, decay=0.9, sustain=0.35),
                  FMOp(1, 0.35, decay=0.4, sustain=0.2), FMOp(1, 0.8, decay=0.8, sustain=0.4)],
                 algorithm=4, root="C-5", duration=1.2, name="FM e-piano")
brass = chip.fm([FMOp(1, 1.1, attack=0.04, decay=0.3, sustain=0.6), FMOp(1, 1.0, attack=0.03, decay=0.6, sustain=0.7),
                 FMOp(2, 0.5, attack=0.05, decay=0.3, sustain=0.5), FMOp(1, 0.9, attack=0.03, decay=0.5, sustain=0.7)],
                algorithm=4, feedback=0.25, root="C-5", duration=1.0, name="FM brass")
bell = chip.fm([FMOp(7, 0.6, decay=0.2, sustain=0.1), FMOp(1, 1.0, decay=0.6, sustain=0.2),
                FMOp(3, 0.3, decay=0.3, sustain=0.1), FMOp(1, 0.6, decay=0.6, sustain=0.2)],
               algorithm=4, root="C-6", duration=1.0, name="FM bell")

bass = song.add_instrument("FM slap bass", slap_bass, volume=58, envelope=chip.adsr(0, 4, 48, 6))
lead = song.add_instrument("FM e-piano lead", epiano, volume=46, envelope=chip.adsr(0, 30, 30, 10), vibrato=(8, 3, 60))
horns = song.add_instrument("FM brass", brass, volume=30, envelope=chip.adsr(2, 8, 44, 8))
chime = song.add_instrument("FM bell", bell, volume=28, envelope=chip.adsr(0, 20, 16, 12))
psg = song.add_instrument("PSG square", chip.square(amplitude=0.5), volume=22, envelope=chip.adsr(0, 6, 30, 4))
kick = song.add_instrument("DAC kick", chip.kick(rate=8000, crush=8, start_hz=180), volume=60)
snare = song.add_instrument("DAC snare", chip.snare(rate=8000, crush=8), volume=48)
hat = song.add_instrument("PSG noise hat", chip.noise(periodic=False), volume=18, envelope=chip.envelope([(0, 64), (2, 0)]))

FM_BASS, FM_LEAD, FM_CH1, FM_CH2, FM_BELL, DAC, PSG1, NOISE = range(8)
for ch, (name, pan) in enumerate([("FM1 bass", 128), ("FM2 lead", 128), ("FM3 brass", 64), ("FM4 brass", 192),
                                  ("FM5 bell", 160), ("FM6 DAC", 128), ("PSG1", 96), ("PSG noise", 160)]):
    song.channels[ch].update(name=name, pan=pan)

# Chords: (bass root, [brass voicing]) per bar.
VERSE = [("D-3", ["F#5", "A-5", "C#6"]), ("B-2", ["F#5", "A-5", "D-6"]),
         ("G-2", ["F#5", "B-5", "D-6"]), ("A-2", ["E-5", "A-5", "C#6"])]
CHORUS = [("E-3", ["G-5", "B-5", "D-6"]), ("A-2", ["G-5", "C#6", "E-6"]),
          ("F#2", ["F#5", "A-5", "C#6"]), ("B-2", ["F#5", "B-5", "D-6"])]

BASS_RHYTHM = "n.o..n.on.o.n.oo"   # syncopated: root / octave


def bassline(p, prog):
    for bar, (root, _) in enumerate(prog):
        for i, c in enumerate(BASS_RHYTHM):
            if c in "no":
                p.set(bar * 16 + i, FM_BASS, notes.transpose(root, 12 if c == "o" else 0), bass)


def stabs(p, prog, rhythm="..x..x....x..x.."):
    for bar, (_, voicing) in enumerate(prog):
        for i, c in enumerate(rhythm):
            if c == "x":
                p.set(bar * 16 + i, FM_CH1, voicing[0], horns)
                p.set(bar * 16 + i, FM_CH2, voicing[2], horns)
                p.set(bar * 16 + i + 2, FM_CH1, "===")
                p.set(bar * 16 + i + 2, FM_CH2, "===")


def psg_arps(p, prog):
    """PSG square: broken-chord eighths through the brass voicing."""
    for bar, (_, voicing) in enumerate(prog):
        for k, i in enumerate(range(0, 16, 2)):
            p.set(bar * 16 + i, PSG1, voicing[k % 3], psg)


def drums(p, bars=4, fill=True):
    for bar in range(bars):
        steps = "k..k s.k. .kk. s..s" if not (fill and bar == bars - 1) else "k..k s.k. s.ss ssss"
        steps = steps.replace(" ", "")
        for i, c in enumerate(steps):
            row = bar * 16 + i
            if c == "k":
                p.set(row, DAC, "C-5", kick)
            elif c == "s":
                p.set(row, DAC, "C-5", snare)
        for i in range(0, 16, 2):
            p.set(bar * 16 + i, NOISE, "C-8", hat, volume=24 if i % 4 else 16)


MELODY_A = ("A-5 . D-6 . . F#6 . A-6 . . G-6 . F#6 . E-6 . "
            "F#6 . . . D-6 . . B-5 . . D-6 . F#6 . E-6 . "
            "D-6 . B-5 . . D-6 . G-6 . . F#6 . E-6 . D-6 . "
            "E-6 . . . . . . . C#6 . E-6 . A-6 . G-6 .")
MELODY_B = ("G-6 . . F#6 . E-6 . . B-5 . . . E-6 . G-6 . "
            "A-6 . . G-6 . E-6 . . C#6 . . . A-5 . C#6 . "
            "F#6 . . E-6 . C#6 . . A-5 . . . C#6 . E-6 . "
            "F#6 . . . . . . . . . . . === . . .")

intro = song.patterns[0]
intro.name = "intro"
bassline(intro, VERSE)
drums(intro)
intro.write(FM_BELL, "D-6 . A-6 . D-7 . A-6 . F#6 . A-6 . D-7 . . . " * 2 + "G-6 . B-6 . D-7 . B-6 . A-6 . C#7 . E-7 . . . " * 2,
            instrument=chime)

verse = song.add_pattern(64, name="verse")
bassline(verse, VERSE)
stabs(verse, VERSE)
drums(verse, fill=False)
verse.write(FM_LEAD, MELODY_A, instrument=lead)

chorus = song.add_pattern(64, name="chorus")
bassline(chorus, CHORUS)
stabs(chorus, CHORUS, rhythm="x.....x...x.....")
psg_arps(chorus, CHORUS)
drums(chorus)
chorus.write(FM_LEAD, MELODY_B, instrument=lead)
chorus.write(FM_BELL, MELODY_B, instrument=chime, transpose=12)  # bell doubling an octave up

verse2 = song.duplicate_pattern(verse)
verse2.name = "verse + PSG"
psg_arps(verse2, VERSE)
for r in (4, 5, 6, 20, 21, 22):
    verse2.set_effect(r, FM_LEAD, fx.vibrato(6, 2))

end = song.duplicate_pattern(chorus)
end.name = "chorus (loop)"
end.set_effect(63, FM_BASS, fx.position_jump(1))

song.order = [intro.index, verse.index, chorus.index, verse2.index, end.index]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    song.save(os.path.join(OUT, "ym2612_genesis_speed.it"))
    print(song.render(os.path.join(OUT, "ym2612_genesis_speed.wav")))
