# mptscript: Python scripting for OpenMPT

`mptscript` puts a Python interface on OpenMPT's sound engine, so code can
compose, edit, save and render tracker music. It is aimed at AI coding agents,
in the same way Blender's Python API lets an agent build a 3D model.

- **Create:** build songs from code: instruments, patterns, effects and the order list.
- **Synthesise:** chiptune sounds come built in: NES-style pulse, triangle and noise, wavetables, and synthesised drums.
- **Save:** real module files (`.it`, `.mptm`, `.xm`, `.s3m`, `.mod`) that open in OpenMPT or any tracker.
- **Render:** a `.wav` through OpenMPT's own mixer, plus a loudness and silence report.
- **Load and edit:** works on existing modules, including ones edited by hand in OpenMPT.
- **Inspect:** `describe()` prints a text grid that uses the same syntax scripts write.

## Build and install

This needs Python 3.9 or later and a C++20 compiler. On Windows that's Visual
Studio 2022 with the C++ workload (MFC is not needed). On Linux or macOS it's
GCC 10+ or Clang 12+.

```sh
python -m venv .venv
.venv/Scripts/activate            # Windows (source .venv/bin/activate elsewhere)
pip install scikit-build-core pybind11 cmake ninja numpy pytest
pip install --no-build-isolation -e scripting/python
pytest scripting/python/tests
```

The extension compiles the same engine sources as libopenmpt with
`LIBOPENMPT_BUILD_SCRIPTING` defined. That define keeps file saving, which the
player library normally compiles out (see `common/BuildSettings.h`). It needs no
external dependencies.

numpy is optional but makes rendering long songs much faster.

## Quick start

```python
import mptscript as mpt
from mptscript import chip, fx

song = mpt.Song.new("it", channels=4, title="Hello", tempo=140)
lead = song.add_instrument("Lead", chip.pulse(0.25), envelope=chip.adsr(0, 8, 40, 10))
bass = song.add_instrument("Bass", chip.triangle())
kick = song.add_instrument("Kick", chip.kick())

p = song.patterns[0]
p.write(0, "C-5 . E-5 . G-5 . C-6 . | G-5:J37 . . . === . . .", instrument=lead, step=2)
p.write(1, "C-3 . . . G-2 . . . A-2 . . . F-2 . . .", instrument=bass, step=4)
p.drums(2, "x...x...x...x.x." * 4, kick)

song.save("hello.it")
print(song.render("hello.wav"))
```

```sh
python -m mptscript run scripting/python/examples/chip_demo.py --play
python -m mptscript info scripting/python/examples/chip_demo.it --rows 16
```

See [AGENTS.md](AGENTS.md) for the full API, the cell syntax, effect tables and
tips for composing chiptunes.

## Example songs

Each script ships with the module it writes and a rendered `.wav`, so you can listen
without building anything. Re-running a script reproduces its files byte for byte.

| Script | Sound chip / machine | Output |
|---|---|---|
| `examples/minimal.py` | Generic chip waves | `minimal.it` (written to the current directory) |
| `examples/chip_demo.py` | NES-style, 6 channels | `chip_demo.it`, `.wav` |
| `examples/edit_existing.py` | Edits `chip_demo` in place | `chip_demo_v2.it`, `.wav` |
| `examples/overworld_quest.py` | Ricoh 2A03 (NES), adventure march | `.it`, `.wav` |
| `examples/arena_anthem.py` | Amiga Paula, ProTracker title theme | `.mod`, `.wav` (A500 emulation) |
| `examples/chipsets/opl3_dos_shooter.py` | Yamaha OPL3 FM (real chip emulation), DOS metal | `.mptm`, `.wav` |
| `examples/chipsets/gameboy_korobeiniki.py` | Game Boy APU, "Korobeiniki" (trad.) | `.it`, `.wav` |
| `examples/chipsets/sid_c64_ninja.py` | MOS 6581 SID, 3 voices, filter sweeps | `.it`, `.wav` |
| `examples/chipsets/ay_msx_infiltration.py` | AY-3-8910 / YM2149 (MSX) | `.it`, `.wav` |
| `examples/chipsets/ym2612_genesis_speed.py` | YM2612 4-op FM + SN76489 (Mega Drive) | `.it`, `.wav` |
| `examples/chipsets/snes_spc700_platformer.py` | SPC700 / S-DSP (SNES): BRR + echo | `.it`, `.wav` (32 kHz) |
| `examples/chipsets/zx_beeper_mountain_king.py` | ZX Spectrum beeper, Grieg (public domain) | `.it`, `.wav` |

All tunes are original compositions in the style of their era, except "Korobeiniki" and
"In the Hall of the Mountain King", which are public domain.
