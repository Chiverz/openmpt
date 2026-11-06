"""Chiptune sample synthesis.

Every generator returns a :class:`Wave`: float sample data in [-1, 1] plus the
loop points, C-5 playback rate and suggested resampling mode. Pass it to
``Song.add_instrument``.

Looped single-cycle waves (pulse, triangle, saw, sine, wavetable) are tuned
so that note C-5 sounds as middle C (~261.6 Hz), like any normal instrument.
Drums are one-shots at their native rate on C-5; play higher or lower notes
to re-pitch them.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from typing import List, Optional, Sequence, Tuple

MIDDLE_C_HZ = 261.6255653

__all__ = [
    "Wave", "pulse", "square", "triangle", "saw", "sine", "wavetable", "noise",
    "kick", "snare", "hihat", "tom", "crash", "bitcrush", "envelope", "adsr", "pluck",
]


@dataclass
class Wave:
    data: List[float]
    c5_speed: int
    loop: Optional[Tuple[int, int]] = None
    resampling: str = "default"  # nearest | linear | cubic | sinc | default
    name: str = ""
    channels: int = 1
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.data) // self.channels

    def scaled(self, gain: float) -> "Wave":
        return replace(self, data=[max(-1.0, min(1.0, x * gain)) for x in self.data])


def _cycle(values: Sequence[float], name: str, resampling: str = "nearest") -> Wave:
    n = len(values)
    return Wave(list(values), c5_speed=round(MIDDLE_C_HZ * n), loop=(0, n), resampling=resampling, name=name)


def _quant(x: float, levels: int) -> float:
    """Quantise [-1, 1] into `levels` steps (e.g. 16 for a 4-bit DAC)."""
    q = round((x + 1.0) / 2.0 * (levels - 1))
    return q / (levels - 1) * 2.0 - 1.0


# --- Looped single-cycle waves ----------------------------------------------

def pulse(duty: float = 0.5, length: int = 32, amplitude: float = 0.6) -> Wave:
    """NES/Game Boy pulse channel. duty 0.125, 0.25, 0.5 (square) or 0.75."""
    if not 0.0 < duty < 1.0:
        raise ValueError("duty must be between 0 and 1")
    high = max(1, round(length * duty))
    data = [amplitude if i < high else -amplitude for i in range(length)]
    return _cycle(data, f"pulse {duty * 100:g}%")


def square(length: int = 32, amplitude: float = 0.6) -> Wave:
    return replace(pulse(0.5, length, amplitude), name="square")


def triangle(length: int = 32, steps: int = 16, amplitude: float = 0.8) -> Wave:
    """Stepped triangle like the NES triangle channel (4-bit, 32 steps)."""
    data = []
    for i in range(length):
        t = i / length
        v = 4 * t - 1 if t < 0.5 else 3 - 4 * t
        data.append(_quant(v, steps) * amplitude if steps else v * amplitude)
    return _cycle(data, "triangle")


def saw(length: int = 32, steps: int = 0, amplitude: float = 0.5) -> Wave:
    data = []
    for i in range(length):
        v = 2 * i / length - 1
        data.append((_quant(v, steps) if steps else v) * amplitude)
    return _cycle(data, "saw")


def sine(length: int = 64, steps: int = 0, amplitude: float = 0.7) -> Wave:
    data = []
    for i in range(length):
        v = math.sin(2 * math.pi * i / length)
        data.append((_quant(v, steps) if steps else v) * amplitude)
    return _cycle(data, "sine", resampling="linear" if not steps else "nearest")


def wavetable(values: Sequence[int], bits: int = 4, amplitude: float = 0.7) -> Wave:
    """Game Boy / PC Engine style wavetable from integer samples (0..2**bits-1).

    Example: ``wavetable([0,2,4,6,8,10,12,14,15,15,14,12,10,8,6,4,2,0] ...)``
    """
    top = (1 << bits) - 1
    data = [((v / top) * 2 - 1) * amplitude for v in values]
    return _cycle(data, "wavetable")


def noise(periodic: bool = False, length: int = 32767, rate: int = 22050, amplitude: float = 0.5, seed: int = 1) -> Wave:
    """NES-style 15-bit LFSR noise, looped. periodic=True gives the metallic
    short mode (93-step loop). Higher notes = brighter noise."""
    reg = seed & 0x7FFF or 1
    tap = 6 if periodic else 1
    n = 93 * 4 if periodic else length
    data = []
    for _ in range(n):
        bit = (reg ^ (reg >> tap)) & 1
        reg = (reg >> 1) | (bit << 14)
        data.append(amplitude if reg & 1 else -amplitude)
    return Wave(data, c5_speed=rate, loop=(0, n), resampling="nearest", name="noise (periodic)" if periodic else "noise")


# --- One-shot drums ----------------------------------------------------------

def _env_exp(i: int, n: int, k: float) -> float:
    return math.exp(-k * i / n)


def kick(rate: int = 22050, duration: float = 0.30, start_hz: float = 160.0, end_hz: float = 42.0,
         click: float = 0.3, amplitude: float = 0.95, crush: int = 0, seed: int = 5) -> Wave:
    """Pitch-swept sine kick drum."""
    rnd = random.Random(seed)
    n = int(rate * duration)
    data, phase = [], 0.0
    for i in range(n):
        t = i / n
        f = end_hz + (start_hz - end_hz) * math.exp(-t * 18)
        phase += 2 * math.pi * f / rate
        v = math.sin(phase) * _env_exp(i, n, 5.0)
        if i < rate * 0.004:
            v += click * (rnd.random() * 2 - 1)
        data.append(max(-1.0, min(1.0, v * amplitude)))
    return _finish(Wave(data, c5_speed=rate, name="kick"), crush)


def snare(rate: int = 22050, duration: float = 0.22, tone_hz: float = 185.0, tone: float = 0.45,
          amplitude: float = 0.8, crush: int = 0, seed: int = 7) -> Wave:
    """Noise burst plus a short tone body."""
    rnd = random.Random(seed)
    n = int(rate * duration)
    data = []
    for i in range(n):
        body = math.sin(2 * math.pi * tone_hz * i / rate) * _env_exp(i, n, 14.0) * tone
        hiss = (rnd.random() * 2 - 1) * _env_exp(i, n, 6.0)
        data.append(max(-1.0, min(1.0, (body + hiss * (1 - tone * 0.5)) * amplitude)))
    return _finish(Wave(data, c5_speed=rate, name="snare"), crush)


def hihat(open: bool = False, rate: int = 22050, amplitude: float = 0.5, crush: int = 0, seed: int = 3) -> Wave:
    """High-passed noise; closed (short) or open (longer)."""
    rnd = random.Random(seed)
    duration = 0.28 if open else 0.05
    n = int(rate * duration)
    data, prev = [], 0.0
    for i in range(n):
        x = rnd.random() * 2 - 1
        hp = x - prev
        prev = x
        data.append(max(-1.0, min(1.0, hp * 0.5 * _env_exp(i, n, 4.0 if open else 6.0) * amplitude)))
    return _finish(Wave(data, c5_speed=rate, name="open hat" if open else "closed hat"), crush)


def tom(rate: int = 22050, start_hz: float = 220.0, end_hz: float = 110.0, duration: float = 0.25,
        amplitude: float = 0.85, crush: int = 0) -> Wave:
    w = kick(rate, duration, start_hz, end_hz, click=0.1, amplitude=amplitude, crush=crush)
    w.name = "tom"
    return w


def crash(rate: int = 22050, duration: float = 1.0, amplitude: float = 0.45, crush: int = 0, seed: int = 11) -> Wave:
    rnd = random.Random(seed)
    n = int(rate * duration)
    data, prev = [], 0.0
    for i in range(n):
        x = rnd.random() * 2 - 1
        hp = x - 0.6 * prev
        prev = x
        data.append(max(-1.0, min(1.0, hp * 0.6 * _env_exp(i, n, 3.5) * amplitude)))
    return _finish(Wave(data, c5_speed=rate, name="crash"), crush)


def pluck(base: Wave, duration: float = 0.4, rate: int = 22050, decay: float = 6.0) -> Wave:
    """Render a looped cycle into a decaying one-shot (for non-instrument formats like MOD/S3M)."""
    if not base.loop:
        raise ValueError("pluck() needs a looped single-cycle wave")
    cycle = base.data[base.loop[0]:base.loop[1]]
    cyc_hz = base.c5_speed / len(cycle)
    step = cyc_hz * len(cycle) / rate
    n = int(rate * duration)
    data = [cycle[int(i * step) % len(cycle)] * _env_exp(i, n, decay) for i in range(n)]
    # one-shot whose C-5 is still middle C
    return Wave(data, c5_speed=round(rate * MIDDLE_C_HZ / cyc_hz), name=f"{base.name} pluck", resampling=base.resampling)


def bitcrush(wave: Wave, bits: int = 4) -> Wave:
    """Quantise a wave to 2**bits levels."""
    levels = 1 << bits
    return replace(wave, data=[_quant(x, levels) for x in wave.data], name=f"{wave.name} {bits}bit")


def _finish(w: Wave, crush: int) -> Wave:
    return bitcrush(w, crush) if crush else w


# --- Instrument envelope helpers ---------------------------------------------
# Envelope ticks are tracker ticks (at speed 6 / tempo 125 one tick is 20 ms,
# one row is 6 ticks). Volume envelope values are 0..64.

def envelope(points: Sequence[Tuple[int, int]], sustain: Optional[int] = None,
             loop: Optional[Tuple[int, int]] = None, carry: bool = False) -> dict:
    """Build an envelope dict. ``points`` are (tick, value) pairs with increasing ticks;
    ``sustain`` is a node index held until note-off; ``loop`` is (start_node, end_node)."""
    pts = [(int(t), int(v)) for t, v in points]
    if any(b[0] <= a[0] for a, b in zip(pts, pts[1:])):
        raise ValueError("envelope ticks must be strictly increasing")
    return {
        "points": pts,
        "enabled": True,
        "carry": carry,
        "sustain": (sustain, sustain) if sustain is not None else None,
        "loop": tuple(loop) if loop else None,
    }


def adsr(attack: int = 0, decay: int = 6, sustain: int = 40, release: int = 12, peak: int = 64) -> dict:
    """Volume envelope from attack/decay/release lengths in ticks and a 0..64 sustain level.
    The sustain level is held until a note-off (``===``) arrives."""
    pts = [(0, 0 if attack else peak)]
    t = 0
    if attack:
        t += attack
        pts.append((t, peak))
    t += max(1, decay)
    pts.append((t, sustain))
    sustain_node = len(pts) - 1
    t += max(1, release)
    pts.append((t, 0))
    return envelope(pts, sustain=sustain_node)
