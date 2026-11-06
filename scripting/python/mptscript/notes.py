"""Note names, numbers and a little music theory.

OpenMPT note numbers: 1 = C-0 ... 61 = C-5 ... 120 = B-9.
C-5 is "middle C" (MIDI 60). Special values: note off (``===``),
note cut (``^^^``), note fade (``~~~``).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Union

from . import _core

NONE = _core.NOTE_NONE
MIN = _core.NOTE_MIN
MAX = 120  # highest note any supported format can store (B-9)
MIDDLE_C = _core.NOTE_MIDDLEC  # C-5
OFF = _core.NOTE_KEYOFF
CUT = _core.NOTE_NOTECUT
FADE = _core.NOTE_FADE

_NAMES = ["C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-", "A#", "B-"]
_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_SPECIAL_IN = {
    "===": OFF, "==": OFF, "OFF": OFF,
    "^^^": CUT, "^^": CUT, "CUT": CUT,
    "~~~": FADE, "~~": FADE, "FADE": FADE,
}
_EMPTY = {"", ".", "..", "...", "---", "-"}
_NOTE_RE = re.compile(r"^([A-Ga-g])([-#b]?)(-?\d)$")

NoteLike = Union[str, int, None]


def parse(note: NoteLike) -> int:
    """Convert a note spec to an OpenMPT note number.

    Accepts tracker names (``"C-5"``, ``"C#4"``), plain names (``"C5"``,
    ``"Bb3"``), specials (``"==="``/``"off"``, ``"^^^"``/``"cut"``,
    ``"~~~"``/``"fade"``), empty markers (``"..."``, ``None``) and ints
    (taken as OpenMPT note numbers).
    """
    if note is None:
        return NONE
    if isinstance(note, int):
        if note in (NONE, OFF, CUT, FADE) or MIN <= note <= MAX:
            return note
        raise ValueError(f"note number out of range: {note}")
    s = note.strip()
    if s in _EMPTY:
        return NONE
    if s.upper() in _SPECIAL_IN:
        return _SPECIAL_IN[s.upper()]
    m = _NOTE_RE.match(s)
    if not m:
        raise ValueError(f"cannot parse note {note!r} (expected e.g. 'C-5', 'C#4', 'Bb3', '===', '^^^')")
    letter, acc, octave = m.groups()
    semi = _SEMITONE[letter.upper()] + (1 if acc == "#" else -1 if acc == "b" else 0)
    value = int(octave) * 12 + semi + MIN
    if not MIN <= value <= MAX:
        raise ValueError(f"note {note!r} out of range C-0..B-9")
    return value


def name(note: int) -> str:
    """OpenMPT-style 3-character name for a note number (``'C-5'``, ``'==='``, ``'...'``)."""
    if note == NONE:
        return "..."
    if note == OFF:
        return "==="
    if note == CUT:
        return "^^^"
    if note == FADE:
        return "~~~"
    if MIN <= note <= 128:
        n = note - MIN
        return f"{_NAMES[n % 12]}{n // 12}"
    return "???"


def from_midi(midi: int) -> int:
    """MIDI note number (60 = middle C) to OpenMPT note number (61 = C-5)."""
    return parse(int(midi) + 1)


def to_midi(note: NoteLike) -> int:
    return parse(note) - 1


def frequency(note: NoteLike, a4: float = 440.0) -> float:
    """Equal-tempered frequency in Hz (A-5 in OpenMPT naming == A4 == 440 Hz)."""
    return a4 * 2.0 ** ((to_midi(note) - 69) / 12.0)


def transpose(note: NoteLike, semitones: int) -> int:
    n = parse(note)
    if not MIN <= n <= MAX:
        return n  # empty / special notes are unaffected
    return max(MIN, min(MAX, n + semitones))


SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "pentatonic": [0, 2, 4, 7, 9],
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "blues": [0, 3, 5, 6, 7, 10],
    "chromatic": list(range(12)),
}

CHORDS = {
    "maj": [0, 4, 7], "min": [0, 3, 7], "dim": [0, 3, 6], "aug": [0, 4, 8],
    "sus2": [0, 2, 7], "sus4": [0, 5, 7], "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11],
    "min7": [0, 3, 7, 10], "5": [0, 7, 12], "oct": [0, 12, 0],
}


def scale(root: NoteLike, kind: str = "major", octaves: int = 1) -> List[str]:
    """Note names of a scale, e.g. ``scale("A-4", "minor")``."""
    r = parse(root)
    steps = SCALES[kind]
    out = [r + 12 * o + s for o in range(octaves) for s in steps] + [r + 12 * octaves]
    return [name(n) for n in out if MIN <= n <= MAX]


def chord(root: NoteLike, kind: str = "maj") -> List[str]:
    """Note names of a chord, e.g. ``chord("C-4", "min7")``."""
    r = parse(root)
    return [name(r + i) for i in CHORDS[kind]]


def names(notes: Iterable[NoteLike]) -> List[str]:
    return [name(parse(n)) for n in notes]
