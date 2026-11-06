"""High-level, agent-friendly API over OpenMPT's engine.

    import mptscript as mpt
    from mptscript import chip, fx

    song = mpt.Song.new("it", channels=4, title="Demo", tempo=140)
    lead = song.add_instrument("Lead", chip.pulse(0.25), envelope=chip.adsr(0, 8, 40, 10))
    p = song.patterns[0]
    p.write(0, "C-5 ... E-5 ... G-5 ... === ...", instrument=lead)
    p[8, 0] = "C-6 01 v48 J37"     # tracker text: note, instrument, volume column, effect
    song.order = [0]
    song.save("demo.it")
    print(song.render("demo.wav"))
"""

from __future__ import annotations

import os
import re
import warnings
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

from . import _core
from . import notes as N
from .chip import Wave
from .effects import Effect

EFFECTS: Dict[str, int] = dict(_core.EFFECTS)
VOLCMDS: Dict[str, int] = dict(_core.VOLCMDS)
_RESAMPLING: Dict[str, int] = dict(_core.RESAMPLING)
_RESAMPLING_NAMES = {v: k for k, v in _RESAMPLING.items()}
NNA = {"cut": 0, "continue": 1, "off": 2, "fade": 3}
_NNA_NAMES = {v: k for k, v in NNA.items()}


# --- Cells -----------------------------------------------------------------

@dataclass
class Cell:
    """One pattern cell. Values are raw engine values (see ``mptscript.EFFECTS``)."""

    note: int = 0
    instr: int = 0
    volcmd: int = 0
    vol: int = 0
    command: int = 0
    param: int = 0

    @property
    def empty(self) -> bool:
        return not (self.note or self.instr or self.volcmd or self.command)

    def astuple(self) -> Tuple[int, int, int, int, int, int]:
        return (self.note, self.instr, self.volcmd, self.vol, self.command, self.param)


CellLike = Union[Cell, str, Tuple, None]

_NOTE_TOKEN = re.compile(r"^([A-Ga-g][-#b]?-?\d|===|\^\^\^|~~~|\.\.\.|---|off|cut|fade)$", re.I)
_INSTR_TOKEN = re.compile(r"^(?:i(\d{1,3})|(\d{1,2}))$")
_VOL_TOKEN = re.compile(r"^([a-z])(\d{1,2})$")
_FX_TOKEN = re.compile(r"^([0-9A-Z#\\:+*?])([0-9A-Fa-f]{2})$")
_EMPTY_TOKENS = {".", "..", "...", "-", "--", "---"}


class Song:
    """A tracker module. Create with :meth:`new` or :meth:`load`."""

    def __init__(self, module: "_core.Module", path: Optional[str] = None):
        self._m = module
        self.path = path
        self._fx_letters: Optional[Dict[str, int]] = None
        self._vol_letters: Optional[Dict[str, int]] = None
        self._seen_messages: set = set()
        self.messages: List[Tuple[str, str]] = []
        self._drain_log()

    def _drain_log(self) -> None:
        """Turn OpenMPT engine log messages (e.g. format limitations hit while saving) into Python
        warnings, once per distinct message, and keep them in ``song.messages``."""
        for level, text in self._m.take_messages():
            self.messages.append((level, text))
            if level in ("warning", "error") and text not in self._seen_messages:
                self._seen_messages.add(text)
                warnings.warn(f"OpenMPT: {text}", stacklevel=3)

    # --- Construction / IO --------------------------------------------------

    @classmethod
    def new(cls, format: str = "it", channels: int = 4, *, title: str = "", artist: str = "",
            tempo: int = 125, speed: int = 6, rows: int = 64) -> "Song":
        """New empty song with one pattern (index 0, `rows` rows) in the order list.

        format: ``it`` (default, recommended), ``mptm`` (OpenMPT extended IT), ``xm`` (FastTracker 2),
        ``s3m`` (Scream Tracker 3, no instruments/envelopes) or ``mod`` (ProTracker, 4 channels typical,
        no volume column, no envelopes).
        """
        s = cls(_core.Module.new(format.lower(), channels))
        s.title = title
        if artist:
            s.artist = artist
        s.tempo = tempo
        s.speed = speed
        if rows != 64:
            s._m.pattern_resize(0, rows)
        return s

    @classmethod
    def load(cls, path: Union[str, os.PathLike]) -> "Song":
        """Load any format OpenMPT can read (it, xm, mod, s3m, mptm, 669, mtm, ...)."""
        path = os.fspath(path)
        with open(path, "rb") as f:
            return cls(_core.Module.load(f.read()), path)

    def save(self, path: Union[str, os.PathLike, None] = None) -> str:
        """Save in the song's own format. Returns the path written."""
        path = os.fspath(path) if path is not None else self.path
        if not path:
            raise ValueError("no path given")
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        self._m.save(os.path.abspath(path), "")
        self.path = path
        self._drain_log()
        return path

    def render(self, path: Union[str, os.PathLike, None] = None, **kwargs) -> "RenderReport":
        """Render to a WAV file (or just analyse if path is None). See :func:`mptscript.render.render`."""
        from .render import render
        return render(self, path, **kwargs)

    def describe(self, patterns: bool = True, max_rows: Optional[int] = None) -> str:
        from .describe import describe
        return describe(self, patterns=patterns, max_rows=max_rows)

    def copy(self) -> "Song":
        """Deep copy through an in-memory save/load round trip."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "copy." + self.format)
            self._m.save(p, "")
            self._m.take_messages()  # already reported by save()/load() of the original
            with open(p, "rb") as f:
                module = _core.Module.load(f.read())
            module.take_messages()
            return Song(module, self.path)

    # --- Song properties --------------------------------------------------------

    format = property(lambda self: self._m.format, doc="it | mptm | xm | s3m | mod")
    title = property(lambda self: self._m.title, lambda self, v: setattr(self._m, "title", v))
    artist = property(lambda self: self._m.artist, lambda self, v: setattr(self._m, "artist", v))
    @property
    def message(self) -> str:
        """Song message / comments, with '\n' line breaks."""
        return self._m.message

    @message.setter
    def message(self, value: str) -> None:
        if value and not self.limits["has_comments"]:
            warnings.warn(f"the {self.format} format cannot store a song message; it will not be saved", stacklevel=2)
        self._m.message = value
    tempo = property(lambda self: self._m.tempo, lambda self, v: setattr(self._m, "tempo", int(v)),
                     doc="Initial tempo (BPM in classic tempo mode with 4 rows per beat at speed 6).")
    speed = property(lambda self: self._m.speed, lambda self, v: setattr(self._m, "speed", int(v)),
                     doc="Initial ticks per row (6 = normal; 3 = double time).")
    global_volume = property(lambda self: self._m.global_volume, lambda self, v: setattr(self._m, "global_volume", int(v)))
    sample_preamp = property(lambda self: self._m.sample_preamp, lambda self, v: setattr(self._m, "sample_preamp", int(v)),
                             doc="Mixing pre-amp (default 48). Raise for quiet songs, lower if many channels clip.")
    rows_per_beat = property(lambda self: self._m.rows_per_beat, lambda self, v: setattr(self._m, "rows_per_beat", int(v)))
    rows_per_measure = property(lambda self: self._m.rows_per_measure, lambda self, v: setattr(self._m, "rows_per_measure", int(v)))
    restart_position = property(lambda self: self._m.restart_position, lambda self, v: setattr(self._m, "restart_position", int(v)))
    linear_slides = property(lambda self: self._m.linear_slides, lambda self, v: setattr(self._m, "linear_slides", bool(v)))

    @property
    def limits(self) -> Dict[str, Any]:
        """Format limits (max channels, rows, samples, ...)."""
        return self._m.limits()

    @property
    def duration(self) -> float:
        """Song length in seconds (one pass through the order list)."""
        return self._m.duration()

    # --- Order list -------------------------------------------------------------

    @property
    def order(self) -> List[int]:
        """Pattern play order. -1 = '---' (end of song), -2 = '+++' (skip)."""
        return self._m.order

    @order.setter
    def order(self, value: Sequence[int]) -> None:
        for p in value:
            if p >= 0 and not self._m.pattern_exists(p):
                raise ValueError(f"order list refers to pattern {p}, which does not exist")
        self._m.order = [int(p) for p in value]

    # --- Channels -------------------------------------------------------------

    @property
    def num_channels(self) -> int:
        return self._m.num_channels

    @num_channels.setter
    def num_channels(self, n: int) -> None:
        """Change the channel count. Pattern data in remaining channels is kept; data in removed
        channels is discarded (it does not come back if the count is raised again)."""
        self._m.num_channels = int(n)

    @property
    def channels(self) -> "_Collection":
        return _Collection(lambda: range(self._m.num_channels), lambda i: Channel(self, i))

    # --- Patterns -----------------------------------------------------------------

    @property
    def patterns(self) -> "_Collection":
        return _Collection(lambda: [i for i in range(self._m.num_patterns) if self._m.pattern_exists(i)],
                           lambda i: Pattern(self, i), check=lambda i: self._m.pattern_exists(i))

    def add_pattern(self, rows: int = 64, index: Optional[int] = None, name: str = "") -> "Pattern":
        """Create a pattern (not added to the order list). Returns it."""
        idx = self._m.pattern_add(rows, -1 if index is None else index)
        p = Pattern(self, idx)
        if name:
            p.name = name
        return p

    def duplicate_pattern(self, pattern: Union[int, "Pattern"]) -> "Pattern":
        return Pattern(self, self._m.pattern_duplicate(int(pattern)))

    def remove_pattern(self, pattern: Union[int, "Pattern"]) -> None:
        self._m.pattern_remove(int(pattern))

    # --- Samples & instruments ------------------------------------------------

    @property
    def has_instruments(self) -> bool:
        return bool(self.limits["has_instruments"])

    @property
    def samples(self) -> "_Collection":
        return _Collection(lambda: range(1, self._m.num_samples + 1), lambda i: Sample(self, i),
                           check=lambda i: 1 <= i <= self._m.num_samples)

    @property
    def instruments(self) -> "_Collection":
        return _Collection(lambda: range(1, self._m.num_instruments + 1), lambda i: Instrument(self, i),
                           check=lambda i: 1 <= i <= self._m.num_instruments)

    def add_sample(self, wave: Wave, name: str = "", *, index: Optional[int] = None, volume: int = 64,
                   pan: Optional[int] = None, vibrato: Optional[Tuple[int, int, int]] = None) -> int:
        """Add a raw sample. Returns its index. Prefer :meth:`add_instrument` for IT/XM/MPTM."""
        idx = index if index is not None else self._m.num_samples + 1
        self._m.sample_set_data(idx, list(wave.data), wave.channels, 16 if self.format != "mod" else 8)
        props: Dict[str, Any] = {"name": (name or wave.name)[:31], "c5_speed": int(wave.c5_speed), "volume": int(volume),
                                 "loop": wave.loop}
        if pan is not None:
            props["pan"] = int(pan)
        if vibrato:
            props.update(vibrato_type=0, vibrato_depth=vibrato[1], vibrato_rate=vibrato[0], vibrato_sweep=vibrato[2])
        self._m.sample_set(idx, props)
        return idx

    def add_instrument(self, name: str, wave: Wave, *, volume: int = 64, envelope: Optional[dict] = None,
                       fadeout: Optional[int] = None, pan: Optional[int] = None, resampling: Optional[str] = None,
                       nna: str = "cut", pitch_envelope: Optional[dict] = None, panning_envelope: Optional[dict] = None,
                       vibrato: Optional[Tuple[int, int, int]] = None, index: Optional[int] = None,
                       filter: Optional[Tuple[int, int]] = None, plugin: Optional[int] = None) -> int:
        """Add an instrument built from `wave` and return the number to use in patterns.

        IT/XM/MPTM: creates a sample *and* an instrument with the same number, so envelopes
        (``envelope=chip.adsr(...)``), fadeout, new-note action and per-instrument resampling work.
        MOD/S3M: creates a sample only; envelope-related options are ignored with a warning.

        volume: default note volume 0..64. pan: 0..256 or None. resampling: nearest (crisp
        chiptune), linear, cubic, sinc, default (falls back to the wave's suggestion).
        vibrato: (rate, depth, sweep) auto-vibrato.
        filter: (cutoff 0..127, resonance 0..127) resonant low-pass (IT/MPTM). For filter sweeps add
          ``pitch_envelope=dict(chip.envelope(...), filter=True)``.
        plugin: route this instrument through an effect plugin slot (see :meth:`add_plugin`).
        """
        if index is None:
            index = max(self._m.num_samples, self._m.num_instruments) + 1
        smp = self.add_sample(wave, name, index=index, volume=volume, vibrato=vibrato)
        if not self.has_instruments:
            ignored = [k for k, v in dict(envelope=envelope, fadeout=fadeout, pitch_envelope=pitch_envelope,
                                          panning_envelope=panning_envelope).items() if v is not None]
            if ignored:
                warnings.warn(f"{self.format} has no instruments; ignoring {', '.join(ignored)}", stacklevel=2)
            if pan is not None:
                self._m.sample_set(smp, {"pan": int(pan)})
            return smp
        self._m.instrument_new(index, smp)
        props: Dict[str, Any] = {"name": name[:31], "nna": NNA[nna]}
        mode = resampling or wave.resampling or "default"
        props["resampling"] = _RESAMPLING[mode]
        if envelope is not None:
            props["volume_envelope"] = envelope
        if pitch_envelope is not None:
            props["pitch_envelope"] = pitch_envelope
        if panning_envelope is not None:
            props["panning_envelope"] = panning_envelope
        if fadeout is not None:
            props["fadeout"] = int(fadeout)
        elif envelope is not None and envelope.get("sustain") is None and self.format == "xm":
            props["fadeout"] = 0
        if pan is not None:
            props["pan"] = int(pan)
        if filter is not None:
            props["filter_cutoff"], props["filter_resonance"] = int(filter[0]), int(filter[1])
        if plugin is not None:
            props["plugin"] = int(plugin)
        self._m.instrument_set(index, props)
        return index

    def add_opl_instrument(self, name: str, patch: Sequence[int], *, volume: int = 64, index: Optional[int] = None,
                           fadeout: Optional[int] = None, nna: str = "cut", pan: Optional[int] = None,
                           plugin: Optional[int] = None) -> int:
        """Add a Yamaha OPL FM instrument (see :mod:`mptscript.opl`). Formats: s3m (OPL2) and mptm (OPL3).
        Returns the number to use in patterns. OPL voices respond to notes, volume and pitch effects
        like samples do; note-off (``===``) starts the release phase."""
        if self.format not in ("s3m", "mptm"):
            raise ValueError(f"OPL instruments need the s3m or mptm format, not {self.format}")
        if index is None:
            index = max(self._m.num_samples, self._m.num_instruments) + 1
        self._m.sample_set_opl(index, [int(b) for b in patch])
        sprops: Dict[str, Any] = {"name": name[:27], "volume": int(volume)}
        if pan is not None and self.format == "s3m":
            sprops["pan"] = int(pan)
        self._m.sample_set(index, sprops)
        if self.has_instruments:
            self._m.instrument_new(index, index)
            props: Dict[str, Any] = {"name": name[:31], "nna": NNA[nna]}
            if fadeout is not None:
                props["fadeout"] = int(fadeout)
            if pan is not None:
                props["pan"] = int(pan)
            if plugin is not None:
                props["plugin"] = int(plugin)
            self._m.instrument_set(index, props)
        return index

    # --- Effect plugins ------------------------------------------------------

    def add_plugin(self, kind: str, *, slot: Optional[int] = None, master: bool = False, dry_mix: bool = False,
                   name: str = "", **params: float) -> int:
        """Insert one of OpenMPT's built-in effect plugins (see :mod:`mptscript.plugins`) and
        return its slot number (1-based). Route channels/instruments to it with
        ``song.channels[i].plugin = slot`` / ``song.instruments[i].plugin = slot``, or set
        ``master=True`` to process the whole mix. Parameters are normalised 0..1, by name."""
        from .plugins import resolve
        t = resolve(kind)
        if slot is None:
            slot = next(i for i in range(1, 251) if self._m.plugin_get(i) is None)
        unknown = set(params) - set(t.params)
        if unknown:
            raise ValueError(f"unknown parameters for {kind}: {sorted(unknown)}; available: {t.params}")
        self._m.plugin_set(slot, t.id1, t.id2, t.library, (name or kind)[:31], [], master, dry_mix)
        for key, value in params.items():
            self._m.plugin_set_param(slot, t.params.index(key), float(value))
        return slot

    def plugin(self, slot: int) -> Optional[Dict[str, Any]]:
        """Plugin info for a slot, with parameters by name where known (None if empty)."""
        from .plugins import TYPES
        d = self._m.plugin_get(slot)
        if d is None:
            return None
        for key, t in TYPES.items():
            if t.id1 == d["id1"] and t.id2 == d["id2"]:
                d["kind"] = key
                d["params"] = dict(zip(t.params, d["params"]))
                break
        return d

    @property
    def plugins(self) -> Dict[int, Dict[str, Any]]:
        """All occupied plugin slots."""
        if not self.limits.get("has_instruments") and self.format != "xm":
            return {}
        out = {}
        for slot in range(1, 251):
            info = self.plugin(slot)
            if info:
                out[slot] = info
        return out

    def set_plugin_param(self, slot: int, param: str, value: float) -> None:
        info = self.plugin(slot)
        if info is None or "kind" not in info:
            raise ValueError(f"no known plugin in slot {slot}")
        from .plugins import TYPES
        self._m.plugin_set_param(slot, TYPES[info["kind"]].params.index(param), float(value))

    def replace_wave(self, sample: int, wave: Wave) -> None:
        """Swap the audio of an existing sample, keeping its name/volume."""
        self._m.sample_set_data(sample, list(wave.data), wave.channels, 16 if self.format != "mod" else 8)
        self._m.sample_set(sample, {"c5_speed": int(wave.c5_speed), "loop": wave.loop})

    # --- Effect-letter tables (for the text cell syntax) -----------------------

    def _letters(self) -> Tuple[Dict[str, int], Dict[str, int]]:
        if self._fx_letters is None:
            fx: Dict[str, int] = {}
            for cmd in sorted(set(EFFECTS.values())):
                if cmd and self._m.supports_effect(cmd):
                    letter = self._m.effect_letter(cmd)
                    if letter not in ("?", " ") and letter not in fx:
                        fx[letter] = cmd
            vol: Dict[str, int] = {}
            for cmd in sorted(set(VOLCMDS.values())):
                if cmd and self._m.supports_vol_effect(cmd):
                    letter = self._m.vol_effect_letter(cmd)
                    if letter not in ("?", " ") and letter not in vol:
                        vol[letter] = cmd
            self._fx_letters, self._vol_letters = fx, vol
        return self._fx_letters, self._vol_letters  # type: ignore[return-value]

    def effect_letters(self) -> Dict[str, str]:
        """Map of effect letter -> engine command name for this format (e.g. IT 'J' -> ARPEGGIO)."""
        names = {v: k for k, v in EFFECTS.items()}
        return {k: names[v] for k, v in self._letters()[0].items()}

    def volume_letters(self) -> Dict[str, str]:
        names = {v: k for k, v in VOLCMDS.items()}
        return {k: names[v] for k, v in self._letters()[1].items()}

    # --- Cell conversion --------------------------------------------------------

    def parse_cell(self, text: str) -> Cell:
        """Parse OpenMPT-style cell text: ``"C-5 01 v48 J37"``. Any part may be
        omitted or written as dots: ``"C-5 01"``, ``"... .. .. A06"``, ``"=== "``,
        ``"v32"``. Instruments >= 100 must be written ``i100``."""
        fx_letters, vol_letters = self._letters()
        cell = Cell()
        tokens = text.split()
        positional = len(tokens) == 4
        for pos, tok in enumerate(tokens):
            if tok in _EMPTY_TOKENS:
                continue
            if (positional and pos == 0) or (not positional and _NOTE_TOKEN.match(tok) and cell.note == 0 and pos == 0):
                cell.note = N.parse(tok)
                continue
            if positional and pos == 1 or (not positional and _INSTR_TOKEN.match(tok) and not cell.instr and not cell.volcmd and not cell.command):
                m = _INSTR_TOKEN.match(tok)
                if not m:
                    raise ValueError(f"bad instrument {tok!r} in cell {text!r}")
                cell.instr = int(m.group(1) or m.group(2))
                continue
            m = _VOL_TOKEN.match(tok)
            if m and (not positional or pos == 2):
                letter, value = m.groups()
                if letter not in vol_letters:
                    raise ValueError(f"volume command {letter!r} not available in {self.format} (have: {''.join(vol_letters)})")
                cell.volcmd, cell.vol = vol_letters[letter], int(value)
                continue
            m = _FX_TOKEN.match(tok)
            if m and (not positional or pos == 3):
                letter, value = m.groups()
                if letter not in fx_letters:
                    raise ValueError(f"effect {letter!r} not available in {self.format} (have: {''.join(fx_letters)})")
                cell.command, cell.param = fx_letters[letter], int(value, 16)
                if cell.command == EFFECTS["SPEED"] and self.format in ("xm", "mod") and cell.param >= 0x20:
                    cell.command = EFFECTS["TEMPO"]  # MOD/XM Fxx: >= 0x20 sets tempo
                continue
            raise ValueError(f"cannot parse token {tok!r} in cell {text!r}")
        return cell

    def format_cell(self, cell: Cell) -> str:
        """Inverse of :meth:`parse_cell`: ``'C-5 01 v48 J37'``."""
        note = N.name(cell.note)
        instr = f"{cell.instr:02d}" if cell.instr else ".."
        if cell.volcmd:
            vol = f"{self._m.vol_effect_letter(cell.volcmd)}{cell.vol:02d}"
        else:
            vol = "..."
        if cell.command:
            eff = f"{self._m.effect_letter(cell.command)}{cell.param:02X}"
        else:
            eff = "..."
        return f"{note} {instr} {vol} {eff}"

    def make_cell(self, note: N.NoteLike = None, instrument: int = 0, volume: Optional[int] = None,
                  effect: Union[Effect, str, Tuple[int, int], None] = None, vol_command: Optional[Tuple[str, int]] = None) -> Cell:
        """Build a cell from friendly parts. `volume` 0..64 goes to the volume column
        (or a Cxx effect in MOD). `effect` may be an fx.* Effect, a letter string like
        'J37', or a raw (command, param) tuple."""
        cell = Cell(note=N.parse(note), instr=int(instrument))
        has_volcol = self.limits["has_volume_column"]
        if vol_command is not None:
            cell.volcmd, cell.vol = VOLCMDS[vol_command[0].upper()], int(vol_command[1])
        if volume is not None:
            if not 0 <= volume <= 64:
                raise ValueError("volume must be 0..64")
            if has_volcol:
                cell.volcmd, cell.vol = VOLCMDS["VOLUME"], int(volume)
            else:
                cell.command, cell.param = EFFECTS["VOLUME"], int(volume)
        if effect is not None:
            if cell.command and not has_volcol:
                warnings.warn(f"{self.format}: no volume column, volume replaced by effect", stacklevel=3)
            if isinstance(effect, Effect):
                if effect.volume_column and has_volcol and not cell.volcmd:
                    cell.volcmd, cell.vol = effect.volume_column
                else:
                    cell.command, cell.param = effect.resolve(self.format)
            elif isinstance(effect, str):
                parsed = self.parse_cell(effect)
                cell.command, cell.param = parsed.command, parsed.param
            else:
                cell.command, cell.param = int(effect[0]), int(effect[1])
            if cell.command and not self._m.supports_effect(cell.command):
                raise ValueError(f"effect {effect!r} is not supported by the {self.format} format")
        return cell

    def _to_cell(self, value: CellLike) -> Cell:
        if value is None:
            return Cell()
        if isinstance(value, Cell):
            cell = Cell(*value.astuple())
        elif isinstance(value, str):
            cell = self.parse_cell(value)
        elif isinstance(value, tuple):
            if len(value) == 6 and all(isinstance(v, int) for v in value):
                cell = Cell(*value)
            else:
                cell = self.make_cell(*value)
        elif isinstance(value, dict):
            cell = self.make_cell(**value)
        else:
            raise TypeError(f"cannot convert {value!r} to a pattern cell")
        return self._adapt_cell(cell)

    def _adapt_cell(self, cell: Cell) -> Cell:
        """Map note-off/cut/fade onto what the format can store:
        S3M has only note cut; MOD has neither, so an ECx/EC0 note-cut effect is used."""
        lim = self.limits
        if cell.note == N.FADE and self.format not in ("it", "mptm"):
            cell.note = N.OFF
        if cell.note == N.OFF and not lim["has_note_off"]:
            cell.note = N.CUT
        if cell.note == N.CUT and not lim["has_note_cut"]:
            cell.note = N.NONE
            if not cell.command:
                cell.command, cell.param = EFFECTS["MODCMDEX"], 0xC0
        return cell

    def __repr__(self) -> str:
        return (f"<Song {self.format} {self.title!r}: {self.num_channels} ch, {len(list(self.patterns))} patterns, "
                f"order {self.order}, {self._m.num_samples} samples, {self._m.num_instruments} instruments>")


class _Collection:
    def __init__(self, keys, make, check=None):
        self._keys, self._make, self._check = keys, make, check

    def __getitem__(self, i: int):
        if self._check is not None and not self._check(i):
            raise IndexError(i)
        if self._check is None and i not in self._keys():
            raise IndexError(i)
        return self._make(i)

    def __iter__(self) -> Iterator:
        return (self._make(i) for i in self._keys())

    def __len__(self) -> int:
        return len(list(self._keys()))


class _DictView:
    """Attribute access over a core get/set dict pair."""

    _fields: Tuple[str, ...] = ()

    def __init__(self, song: Song, index: int):
        object.__setattr__(self, "song", song)
        object.__setattr__(self, "index", index)

    def _get(self) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError

    def _set(self, d: dict) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def __getattr__(self, key: str):
        d = self._get()
        if key in d:
            return d[key]
        raise AttributeError(key)

    def __setattr__(self, key: str, value) -> None:
        if key not in self._get() and key not in self._fields:
            raise AttributeError(f"{type(self).__name__} has no property {key!r}; available: {sorted(self._get())}")
        self._set({key: value})

    def update(self, **props) -> None:
        self._set(props)

    def info(self) -> dict:
        return self._get()

    def __int__(self) -> int:
        return self.index

    __index__ = __int__


class Channel(_DictView):
    """name, pan (0..256), volume (0..64), mute, surround."""

    def _get(self):
        return self.song._m.channel_get(self.index)

    def _set(self, d):
        self.song._m.channel_set(self.index, d)

    def __repr__(self):
        return f"<Channel {self.index} {self._get()}>"


class Sample(_DictView):
    """name, c5_speed, volume (0..64), global_volume, pan, loop (start, end) / None, pingpong,
    sustain_loop, relative_tone, finetune, vibrato_*; length/channels/bits are read-only."""

    def _get(self):
        return self.song._m.sample_get(self.index)

    def _set(self, d):
        self.song._m.sample_set(self.index, d)

    @property
    def data(self) -> List[float]:
        return self.song._m.sample_get_data(self.index)[0]

    def __repr__(self):
        d = self._get()
        return f"<Sample {self.index} {d['name']!r} len={d['length']} c5={d['c5_speed']} vol={d['volume']} loop={d['loop']}>"


class Instrument(_DictView):
    """name, fadeout, global_volume, pan, nna (0 cut,1 continue,2 off,3 fade), resampling,
    volume_envelope / panning_envelope / pitch_envelope (dicts, see chip.envelope),
    keyboard (sample per note), note_map; set `sample` to map every note to one sample."""

    _fields = ("sample",)

    def _get(self):
        return self.song._m.instrument_get(self.index)

    def _set(self, d):
        if "resampling" in d and isinstance(d["resampling"], str):
            d = dict(d, resampling=_RESAMPLING[d["resampling"]])
        if "nna" in d and isinstance(d["nna"], str):
            d = dict(d, nna=NNA[d["nna"]])
        self.song._m.instrument_set(self.index, d)

    def __repr__(self):
        d = self._get()
        env = d["volume_envelope"]
        return (f"<Instrument {self.index} {d['name']!r} samples={sorted(set(d['keyboard']) - {0})} "
                f"env={'on' if env['enabled'] else 'off'} fadeout={d['fadeout']} nna={_NNA_NAMES.get(d['nna'])} "
                f"resampling={_RESAMPLING_NAMES.get(d['resampling'])}>")


# --- Patterns ------------------------------------------------------------------

class Pattern:
    """A pattern: a grid of rows x channels. Index with ``pattern[row, channel]``."""

    def __init__(self, song: Song, index: int):
        self.song = song
        self.index = index

    def __int__(self) -> int:
        return self.index

    __index__ = __int__

    @property
    def rows(self) -> int:
        return self.song._m.pattern_rows(self.index)

    @rows.setter
    def rows(self, n: int) -> None:
        self.song._m.pattern_resize(self.index, int(n))

    @property
    def name(self) -> str:
        return self.song._m.pattern_get_name(self.index)

    @name.setter
    def name(self, v: str) -> None:
        self.song._m.pattern_set_name(self.index, v)

    def __getitem__(self, key: Tuple[int, int]) -> Cell:
        row, ch = key
        return Cell(*self.song._m.cell_get(self.index, row, ch))

    def __setitem__(self, key: Tuple[int, int], value: CellLike) -> None:
        row, ch = key
        cell = self.song._to_cell(value)
        self.song._m.cell_set(self.index, row, ch, *cell.astuple())

    def set(self, row: int, channel: int, note: N.NoteLike = None, instrument: int = 0, volume: Optional[int] = None,
            effect: Union[Effect, str, Tuple[int, int], None] = None, *, merge: bool = False) -> None:
        """Write a cell from friendly parts. With merge=True, only the given parts are
        changed (e.g. add an effect to an existing note)."""
        new = self.song.make_cell(note, instrument, volume, effect)
        if merge:
            old = self[row, channel]
            if note is None:
                new.note = old.note
            if not instrument:
                new.instr = old.instr
            if volume is None and not new.volcmd:
                new.volcmd, new.vol = old.volcmd, old.vol
            if effect is None and not new.command:
                new.command, new.param = old.command, old.param
        new = self.song._adapt_cell(new)
        self.song._m.cell_set(self.index, row, channel, *new.astuple())

    def set_effect(self, row: int, channel: int, effect: Union[Effect, str, Tuple[int, int]]) -> None:
        """Put an effect on a row, keeping the note/instrument/volume there."""
        self.set(row, channel, effect=effect, merge=True)

    def write(self, channel: int, sequence: Union[str, Sequence[Any]], instrument: int = 0, *, start: int = 0,
              step: int = 1, volume: Optional[int] = None, transpose: int = 0, clear: bool = False) -> int:
        """Write a note sequence down one channel, one token per `step` rows.

        Tokens (whitespace separated): a note (``C-5``, ``C#4``, ``Bb3``), ``.``/``...`` for an
        empty row, ``===``/``off`` note off, ``^^^``/``cut`` note cut. Extra cell parts can be
        attached with ``:`` e.g. ``C-5:v32:J37`` or ``...:A03`` (effect on an empty row). ``|``
        is ignored (use it as a bar line). A list of notes/None/Cells is also accepted.
        Returns the row after the last token.
        """
        tokens = sequence.split() if isinstance(sequence, str) else list(sequence)
        tokens = [t for t in tokens if t != "|"]
        if clear:
            self.clear(channels=[channel])
        row = start
        for tok in tokens:
            if row >= self.rows:
                raise ValueError(f"sequence runs past the end of pattern {self.index} ({self.rows} rows) at token {tok!r}")
            if isinstance(tok, Cell):
                self[row, channel] = tok
            elif tok is None:
                pass
            elif isinstance(tok, (int, str)):
                parts = str(tok).split(":") if isinstance(tok, str) else [tok]
                head, extras = parts[0], parts[1:]
                note = N.parse(head)
                if transpose:
                    note = N.transpose(note, transpose)
                if note or extras:
                    instr = instrument if N.MIN <= note <= N.MAX else 0
                    cell = self.song.make_cell(note, instr, volume if N.MIN <= note <= N.MAX else None)
                    for extra in extras:
                        part = self.song.parse_cell(extra)
                        if part.instr:
                            cell.instr = part.instr
                        if part.volcmd:
                            cell.volcmd, cell.vol = part.volcmd, part.vol
                        if part.command:
                            cell.command, cell.param = part.command, part.param
                    self[row, channel] = cell
            else:
                raise TypeError(f"bad sequence token {tok!r}")
            row += step
        return row

    def drums(self, channel: int, steps: str, instrument: int, *, note: N.NoteLike = "C-5", start: int = 0,
              step: int = 1, volume: Optional[int] = None, accent: int = 64, ghost: int = 24) -> None:
        """Step-sequencer string, one char per `step` rows: ``x`` hit, ``X`` accent,
        ``o`` ghost (quiet), ``r`` roll (retrigger), ``.``/``-`` rest; spaces and ``|`` ignored.

        Example: ``p.drums(3, "x...x...x.x.x...", kick)``
        """
        from . import effects as fx
        row = start
        for ch in steps:
            if ch in " |":
                continue
            if row >= self.rows:
                raise ValueError(f"drum steps run past the end of pattern {self.index}")
            if ch in "xXor":
                vol = {"x": volume, "X": accent, "o": ghost, "r": volume}[ch]
                eff = fx.retrig(3) if ch == "r" else None
                self.set(row, channel, note, instrument, vol, eff)
            elif ch not in ".-_":
                raise ValueError(f"unknown drum step {ch!r} (use x X o r . -)")
            row += step

    def clear(self, rows: Optional[Iterable[int]] = None, channels: Optional[Iterable[int]] = None) -> None:
        if rows is None and channels is None:
            self.song._m.pattern_clear(self.index)
            return
        rows = list(range(self.rows)) if rows is None else list(rows)
        channels = list(range(self.song.num_channels)) if channels is None else list(channels)
        for r in rows:
            for c in channels:
                self.song._m.cell_set(self.index, r, c)

    def transpose(self, semitones: int, channels: Optional[Iterable[int]] = None) -> None:
        """Shift all notes (not note-offs) in the given channels."""
        channels = list(range(self.song.num_channels)) if channels is None else list(channels)
        for r in range(self.rows):
            for c in channels:
                cell = self[r, c]
                if N.MIN <= cell.note <= N.MAX:
                    cell.note = N.transpose(cell.note, semitones)
                    self[r, c] = cell

    def copy_from(self, other: Union["Pattern", int], channels: Optional[Iterable[int]] = None,
                  dest_channels: Optional[Iterable[int]] = None) -> None:
        """Copy cells from another pattern of this song (optionally remapping channels)."""
        src = other if isinstance(other, Pattern) else Pattern(self.song, int(other))
        channels = list(range(self.song.num_channels)) if channels is None else list(channels)
        dest = channels if dest_channels is None else list(dest_channels)
        for r in range(min(self.rows, src.rows)):
            for c_src, c_dst in zip(channels, dest):
                self[r, c_dst] = src[r, c_src]

    def cells(self, channel: Optional[int] = None) -> Iterator[Tuple[int, int, Cell]]:
        """Iterate (row, channel, cell) over non-empty cells."""
        data = self.song._m.pattern_get_data(self.index)
        nch = self.song.num_channels
        for i in range(0, len(data), 6):
            cell = Cell(*data[i:i + 6])
            r, c = divmod(i // 6, nch)
            if (channel is None or c == channel) and not cell.empty:
                yield r, c, cell

    def to_text(self, rows: Optional[Iterable[int]] = None, channels: Optional[Iterable[int]] = None,
                row_numbers: bool = True) -> str:
        """OpenMPT-style text grid; each cell is ``NOTE INS VOL EFF``."""
        from .describe import pattern_text
        return pattern_text(self, rows=rows, channels=channels, row_numbers=row_numbers)

    def __repr__(self) -> str:
        return f"<Pattern {self.index} {self.name!r} {self.rows} rows>"
