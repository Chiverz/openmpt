"""edit_existing.py - change a song that already exists (made by a script or by hand in OpenMPT).

This is the pattern an agent follows for requests like "make it faster, drop the
bass an octave and add an echo of the lead":

  1. load the module and read ``song.describe()`` to see what is there
  2. edit cells / instruments / order in place
  3. save under a new name and render to listen

Run after chip_demo.py:  python -m mptscript run examples/edit_existing.py
"""

import os
import sys

import mptscript as mpt
from mptscript import chip, fx

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("MPTSCRIPT_OUT", HERE)
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT, "chip_demo.it")
dst = os.path.join(OUT, "chip_demo_v2.it")

song = mpt.Song.load(src)
print(song.describe(patterns=False))

# Find channels by name rather than hard-coding numbers.
by_name = {ch.name: ch.index for ch in song.channels}
lead_ch, bass_ch = by_name["Lead"], by_name["Bass"]

# 1. Faster.
song.tempo = song.tempo + 15

# 2. Bass down an octave everywhere.
for pat in song.patterns:
    pat.transpose(-12, channels=[bass_ch])

# 3. Add a channel that echoes the lead 3 rows later, quieter, on a thinner pulse.
song.num_channels += 1
echo_ch = song.num_channels - 1
song.channels[echo_ch].update(name="Echo", pan=200)
echo = song.add_instrument("Echo 12.5%", chip.pulse(0.125), volume=20, envelope=chip.adsr(0, 6, 16, 6))
for pat in song.patterns:
    for row, ch, cell in list(pat.cells(lead_ch)):
        if row + 3 < pat.rows and mpt.notes.MIN <= cell.note <= mpt.notes.MAX:
            pat.set(row + 3, echo_ch, cell.note, echo)

# 4. End the song with a short fade on the last pattern.
last = song.patterns[song.order[-1]]
last.set_effect(last.rows - 8, by_name["Arp"], fx.vol_slide(down=8))

song.save(dst)
print(song.render(os.path.splitext(dst)[0] + ".wav"))
