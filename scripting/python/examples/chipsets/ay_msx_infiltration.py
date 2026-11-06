"""ay_msx_infiltration.py - General Instrument AY-3-8910 / Yamaha YM2149 (MSX PSG) stealth-action theme,
in the style of late-80s MSX espionage games (Metal Gear era).

Chip:   AY-3-8910 PSG: three square-wave tone generators (50% duty only), one shared LFSR
        noise generator, 16-level logarithmic volume, and a hardware envelope generator that
        composers ran at audio rate as a "buzzer" waveform for gritty basses.
        Recreated with synthesized samples (square, noise, 32-step envelope saw).
Format: IT, 4 channels (on the chip the drum noise is mixed into tone channel C; here it gets
        its own channel so the bass keeps ringing).
Tune:   original. D minor, 130 BPM, military snare.

Run:  python -m mptscript run examples/chipsets/ay_msx_infiltration.py --play
"""

import os

import mptscript as mpt
from mptscript import chip, fx, notes

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MPTSCRIPT_OUT", HERE)

song = mpt.Song.new("it", channels=4, title="Infiltration (PSG)", artist="mptscript", tempo=130, speed=6)
song.sample_preamp = 46

# AY volume is logarithmic: software envelopes step through 16 levels. Approximate the curve.
AY_LEVELS = [round(64 * 10 ** ((v - 15) * 1.5 / 20)) if v else 0 for v in range(16)]  # 1.5 dB per step


def ay_env(levels, sustain=None):
    """Envelope from a list of 4-bit AY volume levels, one per tick (the way MSX drivers did it)."""
    pts = [(i, AY_LEVELS[v]) for i, v in enumerate(levels)]
    return chip.envelope(pts, sustain=sustain)


lead = song.add_instrument("PSG square lead", chip.square(amplitude=0.6), volume=48,
                           envelope=ay_env([15, 14, 13, 13, 12, 12, 12, 0], sustain=6), vibrato=(10, 3, 80))
counter = song.add_instrument("PSG square soft", chip.square(amplitude=0.6), volume=30,
                              envelope=ay_env([13, 12, 11, 10, 9, 9, 0], sustain=5))
buzz = song.add_instrument("Buzzer bass (env saw)", chip.ay_buzzer("saw"), volume=56,
                           envelope=ay_env([15, 15, 14, 14, 13, 13, 0], sustain=5))
buzz_tri = song.add_instrument("Buzzer bass (env tri)", chip.ay_buzzer("triangle"), volume=60)
noise = chip.noise(periodic=False)
snare = song.add_instrument("Noise snare", noise, volume=44, envelope=ay_env([15, 14, 12, 10, 8, 6, 4, 2, 0]))
hat = song.add_instrument("Noise hat", noise, volume=26, envelope=ay_env([12, 6, 0]))
kick = song.add_instrument("Noise+tone kick", chip.sid_drum("kick"), volume=56)

LEAD, CNTR, BASS, DRUM = range(4)
for ch, (name, pan) in enumerate([("A lead", 96), ("B counter", 160), ("C buzzer", 128), ("Noise", 128)]):
    song.channels[ch].update(name=name, pan=pan)

OSTINATO = "D-3 . D-3 . F-3 . D-3 . G-3 . D-3 . F-3 . E-3 ."
OSTINATO_B = "Bb2 . Bb2 . D-3 . Bb2 . A-2 . A-2 . C#3 . E-3 ."
MARCH = "k...s.ss k.h.s.hs"
MARCH_ROLL = "k...s.ss s.s.rrrr"


def drums(p, bars, roll_last=True):
    for bar in range(bars):
        steps = (MARCH_ROLL if roll_last and bar == bars - 1 else MARCH).replace(" ", "")
        for i, c in enumerate(steps):
            row = bar * 16 + i
            if c == "k":
                p.set(row, DRUM, "C-5", kick)
            elif c == "s":
                p.set(row, DRUM, "C-6", snare)
            elif c == "h":
                p.set(row, DRUM, "C-8", hat)
            elif c == "r":
                p.set(row, DRUM, "C-6", snare, effect=fx.retrig(2))


def bass(p, bars):
    for bar, line_ in enumerate(bars):
        p.write(BASS, line_, instrument=buzz, start=bar * 16)


# --- Patterns ------------------------------------------------------------------------------------
intro = song.patterns[0]
intro.name = "intro"
bass(intro, [OSTINATO] * 4)
drums(intro, 4)
intro.set(48, LEAD, "D-6", lead, effect=fx.porta_down(0x08))  # an alarm-like falling square
intro.set(56, LEAD, "===")

a = song.add_pattern(64, name="A")
bass(a, [OSTINATO] * 4)
drums(a, 4, roll_last=False)
a.write(LEAD, "D-6 . . . . . . . A-5 . . . C-6 . D-6 . "
              "F-6 . . . E-6 . D-6 . E-6 . . . . . . . "
              "D-6 . . . . . . . A-5 . . . C-6 . D-6 . "
              "G-6 . . . F-6 . E-6 . C#6 . . . . . === .", instrument=lead)

b = song.add_pattern(64, name="B")
bass(b, [OSTINATO_B] * 4)
drums(b, 4)
b.write(LEAD, "F-6 . . . . . D-6 . Bb5 . . . D-6 . F-6 . "
              "E-6 . . . . . . . C#6 . . . A-5 . . . "
              "F-6 . . . . . G-6 . A-6 . . . G-6 . F-6 . "
              "E-6 . . . . . . . . . . . === . . .", instrument=lead)
# counter-melody in thirds below on channel B
b.write(CNTR, "D-6 . . . . . Bb5 . G-5 . . . Bb5 . D-6 . "
              "C#6 . . . . . . . A-5 . . . E-5 . . . "
              "D-6 . . . . . E-6 . F-6 . . . E-6 . D-6 . "
              "C#6 . . . . . . . . . . . === . . .", instrument=counter)

a2 = song.duplicate_pattern(a)
a2.name = "A + counter"
a2.write(CNTR, "A-5 . . . . . . . F-5 . . . A-5 . A-5 . "
               "D-6 . . . C-6 . A-5 . C-6 . . . . . . . "
               "A-5 . . . . . . . F-5 . . . A-5 . A-5 . "
               "D-6 . . . C-6 . Bb5 . A-5 . . . . . === .", instrument=counter)
for r in (2, 3, 4, 5, 18, 19, 20, 21):
    a2.set_effect(r, LEAD, fx.vibrato(6, 3))

# Bridge: sustained triangle-buzzer bass, fast square arps (the PSG's "fake chords"), snare rolls.
bridge = song.add_pattern(64, name="bridge")
for bar, (root, kind) in enumerate([("D-3", "min"), ("Bb2", "maj"), ("G-2", "min"), ("A-2", "maj")]):
    bridge.set(bar * 16, BASS, root, buzz_tri)
    for i in range(16):
        row = bar * 16 + i
        if i % 8 == 0:
            bridge.set(row, CNTR, notes.transpose(root, 36), counter, effect=fx.chord(kind))
        else:
            bridge.set_effect(row, CNTR, fx.chord(kind))
    bridge.set(bar * 16, DRUM, "C-5", kick)
    bridge.set(bar * 16 + 8, DRUM, "C-6", snare)
for r in range(56, 64):
    bridge.set(r, DRUM, "C-6", snare, volume=30 + (r - 56) * 4)
bridge.write(LEAD, "A-6 . . . . . . . . . . . . . . . "
                   "Bb6 . . . . . . . A-6 . . . G-6 . . . "
                   "G-6 . . . . . . . . . . . F-6 . E-6 . "
                   "E-6 . . . . . . . . . . . . . === .", instrument=lead)
for r in list(range(4, 12)) + list(range(36, 44)) + list(range(52, 60)):
    bridge.set_effect(r, LEAD, fx.vibrato(5, 4))
bridge.set_effect(63, BASS, fx.position_jump(1))

song.order = [intro.index, a.index, b.index, a2.index, b.index, bridge.index]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    song.save(os.path.join(OUT, "ay_msx_infiltration.it"))
    print(song.render(os.path.join(OUT, "ay_msx_infiltration.wav"), interpolation="nearest"))
