"""sid_c64_ninja.py - Commodore 64 SID-style action theme, in the spirit of mid-80s C64 ninja/arcade games.

Chip:   MOS 6581 SID - only 3 voices. Recreated with synthesized samples plus OpenMPT's
        resonant filter:
          * pulse-width modulation (the SID's signature moving pulse) on lead and arps
          * 50 Hz arpeggio chords: at tempo 125 one tracker tick is 20 ms = one PAL frame,
            so Jxy cycles at exactly the C64's frame rate
          * "waveform-switching" drums (noise burst into a falling triangle) that steal the
            bass voice between notes, as real 3-voice C64 tunes do
          * a resonant low-pass filter sweep on the bass (IT instrument filter + filter envelope)
Format: IT, 3 channels.
Tune:   original.

Run:  python -m mptscript run examples/chipsets/sid_c64_ninja.py --play
"""

import os

import mptscript as mpt
from mptscript import chip, fx, notes

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MPTSCRIPT_OUT", HERE)

song = mpt.Song.new("it", channels=3, title="Shadow Path (SID)", artist="mptscript", tempo=125, speed=5)
song.rows_per_beat, song.rows_per_measure = 4, 16   # speed 5: a 16th note is 5 PAL frames (150 BPM)
song.sample_preamp = 52

# --- SID voices ------------------------------------------------------------------------------
lead = song.add_instrument("PWM lead", chip.pwm(cycles=96, depth=0.42), volume=46,
                           envelope=chip.adsr(attack=1, decay=10, sustain=44, release=10), vibrato=(12, 6, 90))
arp = song.add_instrument("PWM arp", chip.pwm(cycles=64, center=0.3, depth=0.2), volume=30,
                          envelope=chip.adsr(attack=0, decay=6, sustain=30, release=3))
bass = song.add_instrument("Filtered saw bass", chip.saw(length=64), volume=60,
                           envelope=chip.adsr(attack=0, decay=8, sustain=40, release=4),
                           filter=(70, 90),  # resonant low-pass...
                           pitch_envelope=dict(chip.envelope([(0, 64), (6, 44), (24, 26)]), filter=True))  # ...swept down
kick = song.add_instrument("SID kick", chip.sid_drum("kick"), volume=62)
snare = song.add_instrument("SID snare", chip.sid_drum("snare"), volume=50)
tom = song.add_instrument("SID tom", chip.sid_drum("tom"), volume=50)

V1, V2, V3 = range(3)  # voice 1: bass + drums, voice 2: arps / counter-melody, voice 3: lead
for ch, name in enumerate(["Voice 1 bass/drums", "Voice 2 arps", "Voice 3 lead"]):
    song.channels[ch].update(name=name, pan=128)  # the C64 is mono

# --- Building blocks ---------------------------------------------------------------------------
PROG_A = [("A-2", "min"), ("A-2", "min"), ("F-2", "maj"), ("G-2", "maj")]
PROG_B = [("D-3", "min"), ("A-2", "min"), ("E-2", "maj"), ("E-2", "maj")]

# Bass voice: 16th pattern per bar. 'n' root, 'o' octave up, 'f' fifth, 'K' kick, 'S' snare, '.' hold.
BASS_BAR = "K.no.nSo.nK.noSo"
BASS_FILL = "K.no.nSoS.TTSSSS"


def voice1(p, prog, fill_last=True):
    for bar, (root, _) in enumerate(prog):
        steps = BASS_FILL if fill_last and bar == len(prog) - 1 else BASS_BAR
        for i, c in enumerate(steps):
            row = bar * 16 + i
            if c in "nof":
                semis = {"n": 0, "o": 12, "f": 7}[c]
                p.set(row, V1, notes.transpose(root, semis), bass)
            elif c == "K":
                p.set(row, V1, "C-5", kick)
            elif c == "S":
                p.set(row, V1, "C-5", snare)
            elif c == "T":
                p.set(row, V1, "G-4" if i < 12 else "C-5", tom)


def arps(p, prog, octave_up=24):
    """Voice 2: continuous 50 Hz arpeggio chords, retriggered on the beat."""
    for bar, (root, kind) in enumerate(prog):
        chord = fx.chord(kind)
        for i in range(16):
            row = bar * 16 + i
            if i % 4 == 0:
                p.set(row, V2, notes.transpose(root, octave_up), arp, effect=chord)
            else:
                p.set_effect(row, V2, chord)


THEME = [  # voice 3, A minor; '.' holds, tokens per 16th
    "A-5 . . . . . E-6 . . . D-6 . C-6 . B-5 .",
    "C-6 . . . . . . . B-5 . A-5 . G-5 . A-5 .",
    "F-5 . . . A-5 . C-6 . F-6 . E-6 . C-6 . A-5 .",
    "B-5 . . . . . . . D-6 . . . G-6 . . .",
]
THEME_B = [
    "F-6 . . . E-6 . D-6 . . . A-5 . . . D-6 .",
    "E-6 . . . . . . . C-6 . B-5 . A-5 . . .",
    "G#5 . . . B-5 . E-6 . . . . . G#6 . . .",
    "B-6 . . . . . . . A-6 . G#6 . F-6 . E-6 .",
]


def lead_line(p, bars, vibrato_rows=()):
    p.write(V3, " ".join(bars), instrument=lead)
    for r in vibrato_rows:
        p.set_effect(r, V3, fx.vibrato(8, 3))


# --- Patterns ---------------------------------------------------------------------------------------
intro = song.patterns[0]
intro.name = "intro"
voice1(intro, PROG_A)
arps(intro, PROG_A)
for bar, (root, _) in enumerate(PROG_A):  # lead voice: rising octave stabs, SID-style "sync" feel
    intro.set(bar * 16 + 12, V3, notes.transpose(root, 36), lead, effect=fx.porta_up(0x10))
    intro.set(bar * 16 + 15, V3, "===")

a = song.add_pattern(64, name="theme A")
voice1(a, PROG_A)
arps(a, PROG_A)
lead_line(a, THEME, vibrato_rows=(3, 4, 5, 20, 21, 22, 52, 53, 54))

b = song.add_pattern(64, name="theme B")
voice1(b, PROG_B)
arps(b, PROG_B)
lead_line(b, THEME_B, vibrato_rows=(20, 21, 22, 52, 53, 54))
b.set(36, V3, "E-6", lead, effect=fx.tone_porta(0x30))  # glide up into the climax

# Solo break: voice 2 drops the arps and plays a fast 16th counter-line, voice 3 holds a long note.
solo = song.add_pattern(64, name="break")
voice1(solo, PROG_A)
RUN = "A-5 C-6 E-6 A-6 G-6 E-6 C-6 E-6 " * 2 + "F-5 A-5 C-6 F-6 E-6 C-6 A-5 C-6 G-5 B-5 D-6 G-6 F#6 D-6 B-5 D-6"
solo.write(V2, RUN, instrument=arp)
solo.set(0, V3, "E-7", lead, effect=fx.vibrato(6, 4))
for r in range(1, 32):
    solo.set_effect(r, V3, fx.vibrato(6, 4))
solo.set(32, V3, "D-7", lead, effect=fx.tone_porta(0x08))
solo.set(60, V3, "===")

end = song.duplicate_pattern(b)
end.name = "theme B (loop)"
end.set_effect(63, V2, fx.position_jump(1))

song.order = [intro.index, a.index, b.index, a.index, solo.index, end.index]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    song.save(os.path.join(OUT, "sid_c64_ninja.it"))
    print(song.render(os.path.join(OUT, "sid_c64_ninja.wav"), stereo_separation=0))
