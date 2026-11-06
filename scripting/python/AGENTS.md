# mptscript: guide for coding agents

`mptscript` drives OpenMPT's real sound engine (`soundlib`) from Python. A script
builds a tracker module, saves it (`.it`, `.mptm`, `.xm`, `.s3m`, `.mod`) and renders a
`.wav`. Anyone can open the module in OpenMPT to listen or edit by hand, and the
next script can load it again. Think of it as `bpy` for chiptune.

## Workflow

1. **New track:** write a script (start from `examples/chip_demo.py`) that builds
   the song, calls `song.save("name.it")` and prints `song.render("name.wav")`.
   Run it with `python -m mptscript run script.py` (add `--play` to hear it on this
   machine).
2. **Check the render report** instead of listening:
   - duration
   - peak and RMS
   - per-second loudness
   - warnings for silence, clipping or a very short song

   Silence usually means a wrong instrument number, an empty order list or notes on
   a muted channel.
3. **Change requests** ("faster", "add a drum fill", "brighter lead"):
   - If you wrote the script, keep it as the source of truth: edit it and re-run.
   - If the song came from elsewhere, or a person edited the `.it` in OpenMPT,
     run `python -m mptscript info song.it` (or `song.describe()`) to read the
     instruments, order list and pattern grid. Then load it, edit it in place and
     save it under a new name (see `examples/edit_existing.py`).
   - Grid cells print in the same syntax that `pattern[row, ch] = "..."` accepts,
     so you can copy rows back.
4. Save each version under a new name (`_v2`, `_v3`, ...) so earlier versions can
   still be heard.

## Core API (`import mptscript as mpt`, `from mptscript import chip, fx, notes`)

```python
song = mpt.Song.new("it", channels=6, title="Name", tempo=150, speed=6, rows=64)
song = mpt.Song.load("song.it")          # reads any format OpenMPT supports
song.save("song.it")                     # always in the song's own format
report = song.render("song.wav", interpolation="sinc", normalize=True, repeat=0, amiga=None)
print(song.describe(max_rows=16))        # text dump for reading a song
song.duration                            # seconds, one pass through the order list
```

**Song properties:**

| Property | Meaning |
|---|---|
| `title`, `artist`, `message` | Text fields stored in the file |
| `tempo` | Song tempo (BPM) |
| `speed` | Ticks per row: 6 is normal, 3 is double time |
| `rows_per_beat`, `rows_per_measure` | Pattern highlighting |
| `global_volume` | 0..256 |
| `sample_preamp` | Mix gain, default 48. Lower it if a dense song clips. |
| `num_channels` | Can be set. Pattern data is kept. |
| `order` | Pattern indices in play order. -1 is `---` (end), -2 is `+++` (skip). |
| `limits` | Format limits: channels, rows, samples, `has_volume_column`, `has_note_off`, ... |

**Timing:** in the default classic tempo mode one tick lasts `2.5 / tempo` seconds,
and one row lasts `speed` ticks. At tempo 125 and speed 6 a row is 0.12 s.
With 4 rows per beat, the tempo value is the BPM.

### Instruments

```python
lead = song.add_instrument("Lead", chip.pulse(0.25), volume=44,
                           envelope=chip.adsr(attack=0, decay=10, sustain=36, release=8),
                           resampling="nearest", nna="cut", pan=None, fadeout=None,
                           vibrato=None)  # (rate, depth, sweep) auto-vibrato
song.instruments[lead].update(fadeout=512)           # edit later
song.samples[lead].volume = 40                      # sample: name, c5_speed, volume, loop, pan, ...
song.replace_wave(lead, chip.pulse(0.125))          # change the timbre, keep the settings
```

- `add_instrument` returns the number to write in patterns.
- In IT, XM and MPTM it creates a sample and an instrument with the same number.
- MOD and S3M have no instruments, so envelope options are ignored with a warning.

**Waves in `chip`:**

| Kind | Generators |
|---|---|
| Looped pitched waves, tuned so C-5 is middle C | `pulse(duty)` with duty 0.125, 0.25, 0.5 or 0.75; `square()`; `triangle()` (4-bit NES style); `saw()`; `sine()`; `wavetable([...4-bit values])`; `noise(periodic=False)` |
| One-shot drums, native pitch at C-5 | `kick()`, `snare()`, `hihat(open=False)`, `tom()`, `crash()` |
| Helpers | `bitcrush(wave, bits)`; `pluck(wave)` for MOD/S3M, which bakes a decay into the sample |

All drums take `crush=bits` for lo-fi grit.

**Envelopes:**
- `chip.adsr(attack, decay, sustain, release)` uses ticks for the times and 0..64 for the level.
- `chip.envelope([(tick, value), ...], sustain=node, loop=(a, b))` builds an arbitrary envelope.
- A sustain point holds until a note-off (`===`). Without one, the note sounds until the next note on the channel.

### Patterns

```python
p = song.patterns[0]                     # pattern 0 exists in a new song and is in the order
q = song.add_pattern(64, name="chorus")  # not added to the order list automatically
q2 = song.duplicate_pattern(q)
song.order = [0, q.index, q.index, q2.index]

p[row, ch] = "C-5 01 v48 J37"            # note, instrument, volume column, effect
p[row, ch] = "C-5 01"                    # any part may be left out
p[row, ch] = "==="                       # note off; "^^^" is note cut; None clears the cell
p.set(row, ch, "C-5", lead, volume=48, effect=fx.vibrato(4, 2))
p.set_effect(row, ch, fx.arpeggio(4, 7)) # add an effect and keep the note
p.write(ch, "C-5 . E-5 . G-5:v32 . === .", instrument=lead, start=0, step=1, transpose=0)
p.drums(ch, "x...x...x.x.x...", kick, note="C-5")   # x hit, X accent, o ghost, r roll, . rest
p.transpose(-12, channels=[2]); p.clear(rows=range(32, 64)); p.copy_from(other, channels=[0], dest_channels=[3])
for row, ch, cell in p.cells(ch): ...    # non-empty cells
print(p.to_text())
```

**Cell text** has the form `NOTE INS VOL EFF`:

- **Notes:** `C-5`, `C#5`, `Db5` and `C5` are all accepted.
- **Instrument:** 2 digits, or `i123` for numbers above 99.
- **Volume column:** a lowercase letter plus 2 decimal digits, e.g. `v48` (volume) or `p32` (pan).
- **Effect:** a letter plus 2 hex digits.
- **Placeholders:** `...`, `..` or `.` mark an empty part.

In `write()`, attach extra cell parts with `:`. For example, `C-5:v32:J37`, or `...:A03` for an effect on an empty row.

**Effect letters depend on the format.** Run `python -m mptscript letters it` for the full list. The common ones:

| Meaning | IT / S3M / MPTM | XM / MOD | Helper |
|---|---|---|---|
| Arpeggio | `Jxy` | `0xy` | `fx.arpeggio(x, y)`, `fx.chord("min")` |
| Portamento up / down | `Fxx` / `Exx` | `1xx` / `2xx` | `fx.porta_up(n)`, `fx.porta_down(n)` |
| Glide to note | `Gxx` | `3xx` | `fx.tone_porta(n)` |
| Vibrato | `Hxy` | `4xy` | `fx.vibrato(speed, depth)` |
| Volume slide | `Dxy` | `Axy` | `fx.vol_slide(up=, down=)` |
| Set volume | vol column `v00`-`v64` | XM `v`; MOD `Cxx` | `volume=` argument |
| Set speed / tempo | `Axx` / `Txx` | `Fxx` (below 0x20 is speed) | `fx.set_speed`, `fx.set_tempo` |
| Pattern break / jump | `Cxx` / `Bxx` | `Dxx` / `Bxx` | `fx.pattern_break`, `fx.position_jump` |
| Note cut / delay | `SCx` / `SDx` | `ECx` / `EDx` | `fx.note_cut(t)`, `fx.note_delay(t)` |
| Retrigger | `Qxy` | XM `Rxy`; MOD `E9x` | `fx.retrig(ticks)` |
| Panning | `Xxx` | `8xx` | `fx.panning(0..255)` |

The `fx.*` helpers pick the right command for the song's format, so prefer them to raw letters.

## Chiptune craft notes

- **Arpeggio lasts one row.** To hold an arpeggiated chord, put `J37`/`fx.chord(...)`
  on every row it should sound. Re-trigger the note only where you want an attack.
- **Typical channel layout:**
  - 2 pulse channels (lead and harmony/arps)
  - 1 triangle bass
  - 1 to 3 drum channels: kick and snare samples, plus noise hats with a short envelope
- **Pulse duty is timbre:** 12.5% is thin and nasal, 25% is the classic NES lead,
  50% is hollow and square.
- **Mix levels:**
  - Keep pulse leads around volume 40 to 48.
  - Keep arps and echo channels quieter (20 to 30).
  - Triangle bass can sit at 64.
  - Lower `song.sample_preamp` (for example to 32) if the report warns about clipping.
- **Echo:** copy a lead line 2 to 4 rows later on a quiet channel (see `edit_existing.py`).
- **Glides:** a note followed by `fx.tone_porta(n)` on the next note slides between them.
  `fx.vibrato(4, 2)` a few rows into a held note sounds expressive.
- **Speed and swing:**
  - **BPM = tempo × 24 / (rows_per_beat × speed)**. With 16th-note rows (4 rows per beat), speed 6 makes BPM equal the tempo, while speed 3 doubles it.
  - Effects and envelopes run per tick, and a tick lasts `2.5 / tempo` seconds. At tempo 125 a tick is 20 ms, one PAL frame, so `Jxy` arpeggios cycle at the C64/NES frame rate.
  - For triplets, use 6 or 12 rows per beat. For swing, use long/short pairs of 4+2 rows (see the SNES example).
  - `fx.note_delay(t)` on off-beats also adds swing.
- **Note ranges:** keep melodies around C-5 to C-7 and bass around C-2 to C-4.
  Pulse and triangle waves work at any pitch.

## Sound chips

OpenMPT emulates two sound chips in its engine:
- the Amiga's Paula (resampling and A500/A1200 filters)
- the Yamaha OPL2/OPL3 FM synthesizer

Everything else is recreated with synthesized samples played through OpenMPT's mixer. Built-in effect plugins (echo, reverb, chorus) fill in hardware effects. `examples/` has one song per chip, and `tests/test_chipsets.py` checks every one.

| Chip (machine) | Example | How it's done |
|---|---|---|
| Ricoh 2A03 (NES) | `overworld_quest.py` | `chip.pulse` / `chip.triangle` / `chip.noise`, 4 channels |
| MOS 8364 Paula (Amiga) | `arena_anthem.py` | `.mod` with 8-bit samples; `render(amiga="a500")` |
| Yamaha OPL3 (PC Sound Blaster) | `chipsets/opl3_dos_shooter.py` | **real FM emulation**: `song.add_opl_instrument(name, opl.PRESETS[...] or opl.patch(...))`, `mptm` (OPL3) or `s3m` (OPL2) |
| Game Boy APU | `chipsets/gameboy_korobeiniki.py` | 2 pulses, 4-bit `chip.wavetable`, noise; hard L/C/R panning |
| MOS 6581 SID (C64) | `chipsets/sid_c64_ninja.py` | 3 channels, `chip.pwm`, `chip.sid_drum`, 50 Hz arpeggios, `filter=(cutoff, resonance)` + filter envelope |
| AY-3-8910 / YM2149 (MSX, Spectrum 128, Atari ST) | `chipsets/ay_msx_infiltration.py` | 50% squares only, `chip.ay_buzzer` bass, log-volume envelopes |
| YM2612 + SN76489 (Mega Drive) | `chipsets/ym2612_genesis_speed.py` | `chip.fm([FMOp...], algorithm=0..7)` 4-op FM, 8-bit DAC drums |
| SPC700 / S-DSP (SNES) | `chipsets/snes_spc700_platformer.py` | `chip.brr()` sample grit, 32 kHz cubic render, `add_plugin("echo")` |
| ZX Spectrum beeper | `chipsets/zx_beeper_mountain_king.py` | one 1-bit square channel |

**OPL FM** (`from mptscript import opl`):
- A voice is a modulator and a carrier: `opl.patch(opl.Op(mult, level, attack, decay, sustain_level, release, wave, ...), opl.Op(...), feedback=0..7, additive=False)`.
- `level` is attenuation, so 0 is loudest.
- Use `wave` 0-3 on OPL2 (S3M); 4-7 are OPL3-only (MPTM).
- A carrier `mult=2` sounds an octave above the written note.
- `opl.PRESETS` holds piano, epiano, organ, brass, strings, flute, bass, slap_bass, dist_guitar, overdrive_guitar, synth_lead, bell, kick, snare, hihat and tom.
- `opl.decode(patch)` reads a loaded song's patch back, and `song.samples[i].opl` holds the bytes.

**Effect plugins** (`from mptscript import plugins`), stored in IT/MPTM/XM:
- `slot = song.add_plugin("echo", wet_dry=0.3, feedback=0.4, left_delay=plugins.ms(190), master=False)` creates a plugin. All parameters are normalised 0..1, and `plugins.TYPES[kind].params` lists their names.
- Route sound through it with `song.channels[i].plugin = slot` or `add_instrument(..., plugin=slot)`. `master=True` processes the whole mix.
- Available kinds: chorus, compressor, distortion, echo, flanger, gargle, i3dl2_reverb, param_eq, waves_reverb, digibooster_echo, symmod_echo.

**Resonant filter** (IT/MPTM):
- `add_instrument(..., filter=(cutoff 0..127, resonance 0..127))` sets a low-pass filter.
- Add `pitch_envelope=dict(chip.envelope([...]), filter=True)` to sweep it.

**Composing by beats** (`mptscript.compose`):
- `line(pattern, ch, [(note, beats), ...], instrument, rows_per_beat=..., gap=rows)` writes notes by length. `"r"` is a rest, and `gap` adds staccato cuts.
- `compose.T` is a triplet eighth.
- `Voice(instr, play="F-5", root="E-3", low=, high=)` writes real pitches for samples that aren't recorded at C-5. MOD needs this because ProTracker only plays C-4..B-6.

**Engine messages:**
- Format limits hit while saving (for example more than 9 OPL channels in S3M) become Python warnings, once per message. The full list is in `song.messages`.
- `song.limits` includes `has_comments`, `has_plugins` and `has_opl`.

## Formats

| Format | When to use | Limits |
|---|---|---|
| `it` (default) | Best all-round choice: instruments, envelopes, volume column, 127 channels | |
| `mptm` | OpenMPT's extended IT, needed only for OpenMPT-specific features | |
| `xm` | FastTracker 2 style | 32 channels, instruments and envelopes |
| `s3m` | Scream Tracker | No instruments or envelopes; note-off is converted to note cut |
| `mod` | ProTracker / Amiga | Typically 4 channels; no volume column, envelopes or note-off (converted to an `EC0` note cut); 8-bit samples |

**Amiga / MOD tips** (see `examples/arena_anthem.py`):

- **Note range:** ProTracker plays only notes C-4..B-6 (OpenMPT naming).
- **Sample tuning:** a sample with C-5 rate 8363 Hz plays at its recorded rate on C-5, and at twice that rate on C-6.
  - Render each sample at `8363 * 2**(semitones_above_C5 / 12)` Hz.
  - Keep a "root" mapping so melodies are written at real pitch and shifted onto the sample.
  - Bass samples are usually recorded low and triggered high.
- **No envelopes:** bake decays into one-shot samples. Shape sustained loops with `fx.vol_slide`, `fx.note_cut` and the `volume=` argument (stored as `Cxx`).
- **One effect per cell:** only one of volume, arpeggio, slide and so on fits in a cell.
- **Panning:** channels are hard-panned Left Right Right Left. Put kick and snare on one channel, hats/FX on another, then bass and lead.
- **Rendering:** `song.render(..., amiga="a500")` emulates Paula's resampling and the A500 output filter.

A song's format is fixed at creation. Saving always uses that format, and
converting between formats is a tracker GUI feature. To change format, rebuild
the song with your script.

## CLI

```
python -m mptscript run script.py [--play]
python -m mptscript info song.it [--rows 16] [--no-patterns]
python -m mptscript render song.it [out.wav] [--interpolation nearest|linear|cubic|sinc] [--amiga a500|a1200] [--repeat N] [--play]
python -m mptscript play out.wav
python -m mptscript letters it|xm|s3m|mod|mptm
```

## Low level

`song._m` is the raw `mptscript._core.Module`. It has dict-based
`sample_get` / `sample_set`, `instrument_get` / `instrument_set`,
`channel_get` / `channel_set`, `cell_get` / `cell_set`, and bulk
`pattern_get_data` / `pattern_set_data` (6 bytes per cell: note, instr, volcmd,
vol, command, param). The engine command numbers are in `mpt.EFFECTS` and
`mpt.VOLCMDS`.
