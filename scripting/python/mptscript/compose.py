"""Composition helpers: write music in beats instead of rows, and map real pitches onto samples.

    from fractions import Fraction as F
    from mptscript.compose import line, Voice, T

    # one bar at 12 rows per beat: dotted-eighth, sixteenth, triplet run, half note
    line(pattern, ch, [("F-5", F(3, 4)), ("Bb5", F(1, 4)), ("C-6", T), ("D-6", T), ("Eb6", T), ("F-6", 2)],
         instrument=lead, rows_per_beat=12)

``Voice`` is for samples whose recorded pitch is not C-5, or for formats with a
narrow note range (ProTracker MOD plays only C-4..B-6): melodies are written at
real pitch and shifted onto the sample.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING, Iterable, Optional, Sequence, Tuple, Union

from . import notes as N

if TYPE_CHECKING:  # pragma: no cover
    from .song import Pattern

Beats = Union[int, float, Fraction]
T = Fraction(1, 3)  # triplet eighth
REST = "r"


def rows(beats: Beats, rows_per_beat: int) -> int:
    """Convert a duration in beats to rows; raises if it does not land on the row grid."""
    r = Fraction(beats).limit_denominator(1000) * rows_per_beat
    if r.denominator != 1:
        raise ValueError(f"{beats} beats does not fit a grid of {rows_per_beat} rows per beat")
    return int(r)


def total_beats(items: Iterable[Tuple[str, Beats]]) -> Fraction:
    return sum((Fraction(b).limit_denominator(1000) for _, b in items), Fraction(0))


class Voice:
    """Maps real pitches onto the notes that make a sample sound at that pitch.

    ``Voice(instr, play="F-5", root="E-3")``: triggering the sample on F-5 sounds E-3.
    ``low``/``high`` bound the notes the format can play (checked in :meth:`note`).
    """

    def __init__(self, instrument: int, play: N.NoteLike = "C-5", root: N.NoteLike = "C-5",
                 low: N.NoteLike = None, high: N.NoteLike = None, volume: Optional[int] = None):
        self.instrument = int(instrument)
        self.offset = N.parse(play) - N.parse(root)
        self.low = N.parse(low) if low else N.MIN
        self.high = N.parse(high) if high else N.MAX
        self.volume = volume

    def note(self, real: N.NoteLike) -> int:
        n = N.parse(real)
        if not N.MIN <= n <= N.MAX:
            return n  # note off / cut / empty pass through
        n += self.offset
        if not self.low <= n <= self.high:
            raise ValueError(f"{N.name(N.parse(real))} needs note {N.name(n)} on this sample, outside "
                             f"{N.name(self.low)}..{N.name(self.high)}")
        return n

    def __int__(self) -> int:
        return self.instrument


def line(pattern: "Pattern", channel: int, items: Sequence[Tuple[str, Beats]], instrument: Union[int, Voice],
         *, start: int = 0, rows_per_beat: Optional[int] = None, volume: Optional[int] = None,
         rest: str = "===", gap: int = 0) -> int:
    """Write (note, beats) pairs down a channel. ``"r"`` is a rest (writes `rest`, default
    note-off). ``gap`` rows before each next note get a note cut (staccato). Returns the end row."""
    rpb = rows_per_beat or pattern.song.rows_per_beat
    voice = instrument if isinstance(instrument, Voice) else None
    instr = int(instrument)
    row = start
    for note, beats in items:
        length = rows(beats, rpb)
        if note == REST:
            if rest:
                pattern.set(row, channel, rest)
        else:
            n = voice.note(note) if voice else N.parse(note)
            vol = volume if volume is not None else (voice.volume if voice else None)
            pattern.set(row, channel, n, instr, vol)
            if gap and length > gap:
                pattern.set(row + length - gap, channel, "^^^")
        row += length
    return row
