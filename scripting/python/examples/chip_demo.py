"""chip_demo.py - a ~30 second NES-style loop built entirely from code.

Run:  python -m mptscript run examples/chip_demo.py --play
Out:  examples/chip_demo.it  (open in OpenMPT to edit by hand)
      examples/chip_demo.wav

Structure: A minor, i-VI-III-VII (Am F C G), 150 BPM, 16 rows per bar.
  pattern 0  intro   - arpeggio chords, bass, drums
  pattern 1  verse   - adds the pulse lead melody
  pattern 2  chorus  - lead up an octave with vibrato, busier drums
  pattern 3  outro   - chords ring out and fade
"""

import os

import mptscript as mpt
from mptscript import chip, fx

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MPTSCRIPT_OUT", HERE)  # songs are written next to this script

song = mpt.Song.new("it", channels=6, title="Chip Demo", artist="mptscript", tempo=150, speed=6)
song.rows_per_beat, song.rows_per_measure = 4, 16
song.sample_preamp = 40

# --- Instruments --------------------------------------------------------------
lead = song.add_instrument("Lead 25%", chip.pulse(0.25), volume=44,
                           envelope=chip.adsr(attack=0, decay=10, sustain=36, release=8))
arp = song.add_instrument("Arp 12.5%", chip.pulse(0.125), volume=30,
                          envelope=chip.adsr(attack=0, decay=6, sustain=24, release=4))
bass = song.add_instrument("Tri Bass", chip.triangle(), volume=64)
kick = song.add_instrument("Kick", chip.kick(crush=6), volume=60)
snare = song.add_instrument("Snare", chip.snare(crush=6), volume=46)
hat = song.add_instrument("Hat", chip.noise(periodic=False), volume=22,
                          envelope=chip.envelope([(0, 64), (3, 0)]))

for ch, (name, pan) in enumerate([("Lead", 112), ("Arp", 160), ("Bass", 128), ("Kick", 128), ("Snare", 128), ("Hats", 96)]):
    song.channels[ch].update(name=name, pan=pan)
LEAD, ARP, BASS, KICK, SNARE, HATS = range(6)

# --- Harmony helpers -----------------------------------------------------------
PROGRESSION = [("A-", "min"), ("F-", "maj"), ("C-", "maj"), ("G-", "maj")]


def chords(p, octave=5, pattern="x...x...x...x..."):
    """One chord per bar on the arp channel, as arpeggio (Jxy) notes.
    Arpeggio only lasts for the row it is on, so every row of the bar gets the
    effect; 'x' rows also retrigger the note."""
    for bar, (root, kind) in enumerate(PROGRESSION):
        for i, hit in enumerate(pattern):
            if hit == "x":
                p.set(bar * 16 + i, ARP, f"{root}{octave}", arp, effect=fx.chord(kind))
            else:
                p.set_effect(bar * 16 + i, ARP, fx.chord(kind))


def bassline(p, octave=3):
    for bar, (root, _) in enumerate(PROGRESSION):
        p.write(BASS, f"{root}{octave} . . {root}{octave} . . {root}{octave + 1} . "
                      f"{root}{octave} . . {root}{octave} . {root}{octave + 1} . .", instrument=bass, start=bar * 16)


def drums(p, busy=False):
    p.drums(KICK, ("x.....x.x.......") * 4 if not busy else ("x.....x.x...x...") * 4, kick)
    p.drums(SNARE, ("....x.......x..." * 3) + ("....x.......x.xr" if busy else "....x.......x..."), snare)
    p.drums(HATS, ("x.x.x.x.x.x.x.x." if not busy else "xxxxxxxxxxxxxxxx") * 4, hat, note="C-7")


# --- Pattern 0: intro ------------------------------------------------------------
intro = song.patterns[0]
intro.name = "intro"
chords(intro)
bassline(intro)
drums(intro)

# --- Pattern 1: verse with melody -------------------------------------------------
verse = song.add_pattern(64, name="verse")
chords(verse)
bassline(verse)
drums(verse)
MELODY = (
    "E-5 . . . A-5 . C-6 . B-5 . A-5 . G-5 . E-5 . | "
    "F-5 . . . A-5 . C-6 . E-6 . D-6 . C-6 . A-5 . | "
    "G-5 . . . C-6 . E-6 . D-6 . C-6 . B-5 . G-5 . | "
    "B-5 . . . D-6 . G-6 . F#6 . D-6 . B-5 . === ."
)
verse.write(LEAD, MELODY, instrument=lead)

# --- Pattern 2: chorus - melody up an octave, vibrato, busier drums ---------------
chorus = song.add_pattern(64, name="chorus")
chords(chorus, octave=6, pattern="x.x.x.x.x.x.x.x.")
bassline(chorus)
drums(chorus, busy=True)
chorus.write(LEAD, MELODY, instrument=lead, transpose=12)
for bar in range(4):
    chorus.set_effect(bar * 16 + 1, LEAD, fx.vibrato(5, 2))   # vibrato on each held downbeat note
chorus.set_effect(62, LEAD, fx.vol_slide(down=4))

# --- Pattern 3: outro -----------------------------------------------------------------
outro = song.add_pattern(32, name="outro")
outro.set(0, ARP, "A-5", arp, effect=fx.chord("min"))
outro.set(0, BASS, "A-2", bass)
outro.set(0, KICK, "C-5", kick)
outro.set(0, LEAD, "A-6", lead, effect=fx.vibrato(4, 3))
for r in range(1, 31):
    outro.set_effect(r, ARP, fx.chord("min"))
outro.set_effect(8, LEAD, fx.vol_slide(down=2))
outro.set_effect(8, BASS, fx.vol_slide(down=2))
outro.set(31, LEAD, "===")
outro.set(31, ARP, "===")
outro.set(31, BASS, "^^^")

song.order = [0, 1, 2, 1, 2, 3]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    song.save(os.path.join(OUT, "chip_demo.it"))
    report = song.render(os.path.join(OUT, "chip_demo.wav"))
    print(song.describe(patterns=False))
    print(report)
