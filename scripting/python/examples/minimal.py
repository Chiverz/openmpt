"""minimal.py - the smallest useful script: one instrument, one pattern, save + render."""

import mptscript as mpt
from mptscript import chip

song = mpt.Song.new("it", channels=2, title="Minimal", tempo=125)
sq = song.add_instrument("Square", chip.square(), envelope=chip.adsr(0, 4, 32, 6))
tri = song.add_instrument("Triangle", chip.triangle())

p = song.patterns[0]                                   # 64 rows, already in the order list
p.write(0, "C-5 E-5 G-5 C-6 G-5 E-5 C-5 ===", instrument=sq, step=4)
p.write(1, "C-3 . G-2 . A-2 . F-2 .", instrument=tri, step=4)

song.save("minimal.it")
print(song.render("minimal.wav"))
