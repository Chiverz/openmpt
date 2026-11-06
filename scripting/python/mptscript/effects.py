"""Format-independent effect helpers.

Each helper returns an :class:`Effect` that is resolved against the song's
format when written into a pattern, so ``fx.note_cut(3)`` becomes ``SC3`` in
IT/S3M and ``EC3`` in XM/MOD. Effect columns can also be written as raw
tracker text (``"J37"`` in IT, ``"037"`` in XM); see :mod:`mptscript.song`.

Parameter ranges follow the tracker conventions: volumes 0..64,
panning 0..255, speeds/depths as nibbles 0..15.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from . import _core
from .notes import CHORDS

E = _core.EFFECTS
V = _core.VOLCMDS

_IT_LIKE = ("it", "mptm", "s3m")


def _nib(hi: int, lo: int) -> int:
    if not (0 <= hi <= 15 and 0 <= lo <= 15):
        raise ValueError(f"effect nibbles must be 0..15, got {hi}, {lo}")
    return (hi << 4) | lo


def _byte(v: int) -> int:
    if not 0 <= v <= 255:
        raise ValueError(f"effect parameter must be 0..255, got {v}")
    return v


@dataclass(frozen=True)
class Effect:
    """An effect-column command, resolved per format by ``resolve(fmt)``."""

    label: str
    _resolve: Callable[[str], Tuple[int, int]]
    # If set, the effect is best expressed in the volume column (e.g. set volume in IT).
    volume_column: Optional[Tuple[int, int]] = None

    def resolve(self, fmt: str) -> Tuple[int, int]:
        return self._resolve(fmt)

    def __repr__(self) -> str:
        return f"fx.{self.label}"


def _const(label: str, cmd: str, param: int) -> Effect:
    c = E[cmd]
    return Effect(label, lambda fmt: (c, param))


def raw(command: str, param: int) -> Effect:
    """Engine command by name (see ``mptscript.EFFECTS``) with a raw parameter byte."""
    if command.upper() not in E:
        raise ValueError(f"unknown effect command {command!r}; known: {sorted(E)}")
    return _const(f"raw({command!r}, 0x{param:02X})", command.upper(), _byte(param))


def arpeggio(x: int, y: int) -> Effect:
    """Arpeggio: cycle base note, +x, +y semitones every tick (the chiptune chord)."""
    return _const(f"arpeggio({x}, {y})", "ARPEGGIO", _nib(x, y))


def chord(kind: str = "maj") -> Effect:
    """Arpeggio for a named chord: maj, min, dim, aug, sus2, sus4, 5, oct, ..."""
    steps = CHORDS[kind]
    return arpeggio(min(steps[1], 15), min(steps[2], 15))


def porta_up(speed: int) -> Effect:
    return _const(f"porta_up({speed})", "PORTAMENTOUP", _byte(speed))


def porta_down(speed: int) -> Effect:
    return _const(f"porta_down({speed})", "PORTAMENTODOWN", _byte(speed))


def tone_porta(speed: int) -> Effect:
    """Glide from the previous note to this row's note."""
    return _const(f"tone_porta({speed})", "TONEPORTAMENTO", _byte(speed))


def vibrato(speed: int, depth: int) -> Effect:
    return _const(f"vibrato({speed}, {depth})", "VIBRATO", _nib(speed, depth))


def tremolo(speed: int, depth: int) -> Effect:
    return _const(f"tremolo({speed}, {depth})", "TREMOLO", _nib(speed, depth))


def vol_slide(up: int = 0, down: int = 0) -> Effect:
    """Volume slide per tick. Use only one of up/down."""
    if up and down:
        raise ValueError("vol_slide: give either up or down, not both")
    return _const(f"vol_slide(up={up}, down={down})", "VOLUMESLIDE", _nib(up, down))


def set_volume(volume: int) -> Effect:
    """Set note volume 0..64. Written to the volume column where the format has one."""
    if not 0 <= volume <= 64:
        raise ValueError("volume must be 0..64")
    return Effect(f"set_volume({volume})", lambda fmt: (E["VOLUME"], volume), volume_column=(V["VOLUME"], volume))


def panning(pan: int) -> Effect:
    """Set channel panning 0 (left) .. 128 (centre) .. 255 (right)."""
    return _const(f"panning({pan})", "PANNING8", _byte(pan))


def offset(position: int) -> Effect:
    """Start the sample at position*256 frames."""
    return _const(f"offset({position})", "OFFSET", _byte(position))


def position_jump(order: int) -> Effect:
    return _const(f"position_jump({order})", "POSITIONJUMP", _byte(order))


def pattern_break(row: int = 0) -> Effect:
    return _const(f"pattern_break({row})", "PATTERNBREAK", _byte(row))


def set_speed(ticks: int) -> Effect:
    """Ticks per row (lower = faster). Default is 6."""
    return _const(f"set_speed({ticks})", "SPEED", _byte(ticks))


def set_tempo(bpm: int) -> Effect:
    """Tempo 32..255 (classic tempo mode: BPM when rows_per_beat == 4 and speed == 6)."""
    return _const(f"set_tempo({bpm})", "TEMPO", _byte(bpm))


def _ext(label: str, nibble_cmd: int, value: int) -> Effect:
    if not 0 <= value <= 15:
        raise ValueError(f"{label}: value must be 0..15")

    def res(fmt: str) -> Tuple[int, int]:
        if fmt in _IT_LIKE:
            return E["S3MCMDEX"], (nibble_cmd << 4) | value
        return E["MODCMDEX"], (nibble_cmd << 4) | value

    return Effect(f"{label}({value})", res)


def note_cut(tick: int) -> Effect:
    """Cut the note after `tick` ticks (staccato / short blips)."""
    return _ext("note_cut", 0xC, tick)


def note_delay(tick: int) -> Effect:
    """Delay the note by `tick` ticks (swing, flams, echoes)."""
    return _ext("note_delay", 0xD, tick)


def pattern_delay(rows: int) -> Effect:
    return _ext("pattern_delay", 0xE, rows)


def retrig(ticks: int, volume_change: int = 0) -> Effect:
    """Retrigger the note every `ticks` ticks (drum rolls). volume_change is the
    IT/XM Qxy/Rxy nibble (0 = none, 1..5 = quieter, 9..D = louder)."""
    if not 1 <= ticks <= 15:
        raise ValueError("retrig: ticks must be 1..15")

    def res(fmt: str) -> Tuple[int, int]:
        if fmt == "mod":
            return E["MODCMDEX"], 0x90 | ticks
        return E["RETRIG"], _nib(volume_change, ticks)

    return Effect(f"retrig({ticks}, {volume_change})", res)


def global_volume(volume: int) -> Effect:
    """Global volume 0..64 (scaled to 0..128 for IT/MPTM)."""
    if not 0 <= volume <= 64:
        raise ValueError("global volume must be 0..64")
    return Effect(f"global_volume({volume})", lambda fmt: (E["GLOBALVOLUME"], volume * 2 if fmt in ("it", "mptm") else volume))


def channel_volume(volume: int) -> Effect:
    """IT/MPTM channel volume 0..64."""
    return _const(f"channel_volume({volume})", "CHANNELVOLUME", _byte(volume))


def key_off(tick: int = 0) -> Effect:
    """XM Kxx key-off after `tick` ticks."""
    return _const(f"key_off({tick})", "KEYOFF", _byte(tick))
