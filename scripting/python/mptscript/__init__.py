"""mptscript - script OpenMPT's sound engine from Python.

Compose, edit, save (.it/.mptm/.xm/.s3m/.mod) and render (.wav) tracker
music from code, the way Blender's ``bpy`` scripts 3D scenes.

    import mptscript as mpt
    from mptscript import chip, fx

    song = mpt.Song.new("it", channels=4, title="Hello", tempo=140)
    lead = song.add_instrument("Lead", chip.pulse(0.25), envelope=chip.adsr(0, 6, 40, 8))
    song.patterns[0].write(0, "C-5 . E-5 . G-5 . C-6 . === ", instrument=lead, step=2)
    song.save("hello.it")
    print(song.render("hello.wav"))

See AGENTS.md next to this package for the full guide.
"""

from . import _core
from . import chip
from . import effects
from . import effects as fx
from . import compose
from . import notes
from . import opl
from . import plugins
from .render import RenderReport, play, render, render_pcm
from .song import EFFECTS, NNA, VOLCMDS, Cell, Channel, Instrument, Pattern, Sample, Song

__version__ = "0.1.0"

new = Song.new
load = Song.load

__all__ = [
    "Song", "Pattern", "Cell", "Channel", "Sample", "Instrument", "RenderReport",
    "new", "load", "render", "render_pcm", "play",
    "chip", "fx", "effects", "notes", "opl", "plugins", "compose", "EFFECTS", "VOLCMDS", "NNA",
]
