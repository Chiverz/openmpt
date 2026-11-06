"""Yamaha OPL2/OPL3 FM instruments (AdLib / Sound Blaster), emulated by OpenMPT's Opal core.

OPL voices are 2-operator FM: a *modulator* bends the phase of a *carrier*
(or, with ``additive=True``, both are simply mixed). Use them in ``s3m`` songs
(OPL2: waveforms 0-3) or ``mptm`` songs (OPL3: waveforms 0-7).

    from mptscript import opl
    piano = song.add_opl_instrument("FM Piano", opl.PRESETS["piano"])
    lead = song.add_opl_instrument("Lead", opl.patch(opl.Op(mult=2, level=18, decay=4),
                                                     opl.Op(mult=1, attack=15, decay=2, sustain_level=4),
                                                     feedback=5))

Operator values follow the chip registers:
  mult 0..15 frequency multiplier (0 = x0.5), level 0..63 attenuation (0 = loudest),
  attack/decay/release 0..15 (15 = fastest), sustain_level 0..15 (0 = loudest),
  wave 0 sine, 1 half-sine, 2 abs-sine, 3 quarter-sine pulses, (OPL3 only:) 4 alternating
  sine, 5 camel sine, 6 square, 7 log-saw; sustain=True holds at sustain_level until note-off.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List

WAVES = {"sine": 0, "half_sine": 1, "abs_sine": 2, "pulse_sine": 3,
         "alt_sine": 4, "camel_sine": 5, "square": 6, "log_saw": 7}


@dataclass(frozen=True)
class Op:
    mult: int = 1
    level: int = 0
    attack: int = 15
    decay: int = 0
    sustain_level: int = 0
    release: int = 5
    wave: int = 0
    sustain: bool = True
    vibrato: bool = False
    tremolo: bool = False
    ksr: bool = False
    ksl: int = 0

    def __post_init__(self):
        for name, lo, hi in [("mult", 0, 15), ("level", 0, 63), ("attack", 0, 15), ("decay", 0, 15),
                             ("sustain_level", 0, 15), ("release", 0, 15), ("wave", 0, 7), ("ksl", 0, 3)]:
            v = getattr(self, name)
            if not lo <= v <= hi:
                raise ValueError(f"OPL operator {name} must be {lo}..{hi}, got {v}")

    def regs(self):
        am_vib = (0x80 if self.tremolo else 0) | (0x40 if self.vibrato else 0) | (0x20 if self.sustain else 0) \
            | (0x10 if self.ksr else 0) | self.mult
        return am_vib, (self.ksl << 6) | self.level, (self.attack << 4) | self.decay, \
            (self.sustain_level << 4) | self.release, self.wave


def patch(modulator: Op, carrier: Op, feedback: int = 0, additive: bool = False) -> List[int]:
    """Build the 12-byte patch OpenMPT stores for an OPL instrument."""
    if not 0 <= feedback <= 7:
        raise ValueError("feedback must be 0..7")
    m, c = modulator.regs(), carrier.regs()
    return [m[0], c[0], m[1], c[1], m[2], c[2], m[3], c[3], m[4], c[4], (feedback << 1) | (1 if additive else 0), 0]


def decode(p: List[int]) -> dict:
    """Inverse of :func:`patch` (for describe() / editing loaded songs)."""
    def op(i):
        return Op(mult=p[i] & 15, level=p[2 + i] & 63, ksl=p[2 + i] >> 6, attack=p[4 + i] >> 4, decay=p[4 + i] & 15,
                  sustain_level=p[6 + i] >> 4, release=p[6 + i] & 15, wave=p[8 + i] & 7, sustain=bool(p[i] & 0x20),
                  vibrato=bool(p[i] & 0x40), tremolo=bool(p[i] & 0x80), ksr=bool(p[i] & 0x10))
    return {"modulator": op(0), "carrier": op(1), "feedback": (p[10] >> 1) & 7, "additive": bool(p[10] & 1)}


def brighter(p: List[int], amount: int = 6) -> List[int]:
    """More modulator output (lower attenuation) = brighter / grittier tone."""
    d = decode(p)
    return patch(replace(d["modulator"], level=max(0, d["modulator"].level - amount)), d["carrier"], d["feedback"], d["additive"])


# A small General-MIDI-flavoured bank in the style of DOS-era AdLib/Sound Blaster drivers.
PRESETS: Dict[str, List[int]] = {
    "piano": patch(Op(mult=1, level=24, attack=15, decay=3, sustain_level=5, release=4, sustain=False, ksl=1),
                   Op(mult=1, level=0, attack=15, decay=2, sustain_level=4, release=4, sustain=False), feedback=3),
    "epiano": patch(Op(mult=14, level=36, attack=15, decay=5, sustain_level=10, release=5, sustain=False),
                    Op(mult=1, level=0, attack=15, decay=2, sustain_level=6, release=5, sustain=False), feedback=0),
    "organ": patch(Op(mult=2, level=20, attack=15, decay=0, sustain_level=0, release=7),
                   Op(mult=1, level=0, attack=15, decay=0, sustain_level=0, release=7), feedback=2, additive=True),
    "brass": patch(Op(mult=1, level=16, attack=9, decay=2, sustain_level=2, release=6, vibrato=True),
                   Op(mult=1, level=0, attack=11, decay=1, sustain_level=1, release=6, vibrato=True), feedback=6),
    "strings": patch(Op(mult=1, level=22, attack=6, decay=1, sustain_level=1, release=5, vibrato=True),
                     Op(mult=1, level=2, attack=7, decay=1, sustain_level=1, release=5, vibrato=True), feedback=4),
    "flute": patch(Op(mult=1, level=40, attack=8, decay=0, sustain_level=0, release=6, tremolo=True),
                   Op(mult=1, level=0, attack=8, decay=0, sustain_level=0, release=6, vibrato=True), feedback=7),
    "bass": patch(Op(mult=1, level=14, attack=15, decay=4, sustain_level=6, release=8, sustain=False),
                  Op(mult=1, level=0, attack=15, decay=3, sustain_level=3, release=8), feedback=5),
    "slap_bass": patch(Op(mult=3, level=12, attack=15, decay=6, sustain_level=8, release=8, sustain=False),
                       Op(mult=1, level=0, attack=15, decay=3, sustain_level=4, release=8), feedback=6),
    "dist_guitar": patch(Op(mult=1, level=6, attack=15, decay=1, sustain_level=2, release=6, wave=6),
                         Op(mult=1, level=0, attack=15, decay=1, sustain_level=2, release=6, wave=7), feedback=7),
    "overdrive_guitar": patch(Op(mult=1, level=12, attack=15, decay=2, sustain_level=3, release=6, wave=1),
                              Op(mult=2, level=2, attack=15, decay=1, sustain_level=3, release=6, wave=6), feedback=6),
    "synth_lead": patch(Op(mult=1, level=10, attack=15, decay=0, sustain_level=0, release=5, wave=6),
                        Op(mult=1, level=0, attack=15, decay=0, sustain_level=0, release=5, wave=0, vibrato=True), feedback=5),
    "bell": patch(Op(mult=7, level=20, attack=15, decay=4, sustain_level=10, release=4, sustain=False),
                  Op(mult=1, level=0, attack=15, decay=2, sustain_level=8, release=3, sustain=False), feedback=2),
    "kick": patch(Op(mult=0, level=6, attack=15, decay=8, sustain_level=15, release=15, sustain=False),
                  Op(mult=0, level=0, attack=15, decay=6, sustain_level=15, release=15, sustain=False), feedback=6),
    "snare": patch(Op(mult=12, level=0, attack=15, decay=7, sustain_level=15, release=15, sustain=False, wave=0),
                   Op(mult=1, level=0, attack=15, decay=6, sustain_level=15, release=15, sustain=False, wave=0), feedback=7),
    "hihat": patch(Op(mult=15, level=0, attack=15, decay=10, sustain_level=15, release=15, sustain=False),
                   Op(mult=14, level=4, attack=15, decay=10, sustain_level=15, release=15, sustain=False), feedback=7),
    "tom": patch(Op(mult=0, level=12, attack=15, decay=6, sustain_level=15, release=15, sustain=False),
                 Op(mult=1, level=0, attack=15, decay=5, sustain_level=15, release=12, sustain=False), feedback=4),
}
