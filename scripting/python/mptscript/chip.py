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


# --- Chip-specific generators --------------------------------------------------------------------

def pwm(cycles: int = 128, period: int = 64, center: float = 0.5, depth: float = 0.4, amplitude: float = 0.55) -> Wave:
    """C64 SID-style pulse-width modulation: a seamless loop of `cycles` pulse periods whose
    duty sweeps sinusoidally (center +/- depth). C-5 plays middle C; the sweep speeds up with pitch."""
    data = []
    for k in range(cycles):
        duty = center + depth * math.sin(2 * math.pi * k / cycles)
        high = max(1, min(period - 1, round(period * duty)))
        data.extend(amplitude if i < high else -amplitude for i in range(period))
    return Wave(data, c5_speed=round(MIDDLE_C_HZ * period), loop=(0, len(data)), resampling="nearest", name="pwm pulse")


def sid_drum(kind: str = "kick", rate: int = 22050, amplitude: float = 0.9, seed: int = 64) -> Wave:
    """C64 drums the SID way: a noise burst for one frame, then a pitch-dropping triangle (kick/tom)
    or noise/pulse mix (snare), the waveform-switching trick of 80s C64 composers."""
    rnd = random.Random(seed)
    frame = rate // 50
    if kind == "kick":
        n, f0, f1, tone = int(rate * 0.22), 220.0, 40.0, "tri"
    elif kind == "tom":
        n, f0, f1, tone = int(rate * 0.25), 300.0, 120.0, "tri"
    elif kind == "snare":
        n, f0, f1, tone = int(rate * 0.20), 260.0, 140.0, "noise"
    else:
        raise ValueError("kind must be kick, tom or snare")
    data, ph = [], 0.0
    for i in range(n):
        t = i / n
        env = (1 - t) ** 1.5
        if i < frame or (tone == "noise" and i % 2):
            v = rnd.random() * 2 - 1
        else:
            ph += (f1 + (f0 - f1) * (1 - t) ** 3) / rate
            v = 4 * abs((ph % 1) - 0.5) - 1 if tone == "tri" else (1.0 if ph % 1 < 0.5 else -1.0)
        data.append(v * env * amplitude)
    return Wave(data, c5_speed=rate, name=f"sid {kind}")


def ay_buzzer(shape: str = "saw", steps: int = 32, amplitude: float = 0.7) -> Wave:
    """AY-3-8910 / YM2149 hardware-envelope 'buzzer' used as an audio-rate waveform (Atari ST,
    MSX and Spectrum basses). shape 'saw' (envelope shapes 8/12) or 'triangle' (10/14); 32 steps = YM2149."""
    if shape == "saw":
        w = saw(length=steps * 2, steps=steps, amplitude=amplitude)
    elif shape == "triangle":
        w = triangle(length=steps * 2, steps=steps, amplitude=amplitude)
    else:
        raise ValueError("shape must be saw or triangle")
    w.name = f"ay buzzer {shape}"
    return w


# YM2612-style operator routing: (modulation sources for operators 1..4, output operators).
FM_ALGORITHMS = {
    0: ({2: [1], 3: [2], 4: [3]}, [4]),
    1: ({3: [1, 2], 4: [3]}, [4]),
    2: ({3: [2], 4: [1, 3]}, [4]),
    3: ({2: [1], 4: [2, 3]}, [4]),
    4: ({2: [1], 4: [3]}, [2, 4]),
    5: ({2: [1], 3: [1], 4: [1]}, [2, 3, 4]),
    6: ({2: [1]}, [2, 3, 4]),
    7: ({}, [1, 2, 3, 4]),
}


@dataclass
class FMOp:
    """One FM operator. ratio = frequency multiple; level = output (carriers) or modulation
    index in cycles (modulators); attack/decay in seconds; sustain = fraction of level held."""
    ratio: float = 1.0
    level: float = 1.0
    attack: float = 0.002
    decay: float = 0.3
    sustain: float = 0.6

    def env(self, t: float) -> float:
        if t < self.attack:
            return t / self.attack
        return self.sustain + (1 - self.sustain) * math.exp(-(t - self.attack) / max(1e-4, self.decay))


def fm(ops: Sequence[FMOp], algorithm: int = 4, feedback: float = 0.0, root: str = "C-5",
       duration: float = 1.2, target_rate: int = 32000, loop_cycles: int = 24, amplitude: float = 0.8,
       name: str = "fm") -> Wave:
    """4-operator FM voice in the style of the Yamaha YM2612 (Mega Drive / Genesis).

    Rendered at `root` with a sample rate that is an exact multiple of the note frequency, so the
    steady-state tail loops seamlessly and held notes keep their timbre (use integer ratios).
    Shape overall volume and release with an instrument envelope.
    """
    from . import notes as _notes
    if len(ops) != 4:
        raise ValueError("fm() needs exactly 4 operators")
    routing, outputs = FM_ALGORITHMS[algorithm]
    f0 = _notes.frequency(root)
    period = max(16, round(target_rate / f0))
    rate = f0 * period
    n = int(rate * duration)
    n -= n % period
    vals = [0.0] * 4
    fb1 = fb2 = 0.0
    data = []
    two_pi = 2 * math.pi
    for i in range(n):
        t = i / rate
        base = i / period
        for k in range(4):
            phase = base * ops[k].ratio
            for src in routing.get(k + 1, ()):
                phase += vals[src - 1] * ops[src - 1].level
            if k == 0 and feedback:
                phase += feedback * (fb1 + fb2) * 0.5
            vals[k] = math.sin(two_pi * phase) * ops[k].env(t)
            if k == 0:
                fb2, fb1 = fb1, vals[0]
        data.append(sum(vals[o - 1] * ops[o - 1].level for o in outputs) / len(outputs))
    peak = max(abs(v) for v in data) or 1.0
    data = [v * amplitude / peak for v in data]
    loop_len = period * loop_cycles
    return Wave(data, c5_speed=round(rate * MIDDLE_C_HZ / f0), loop=(n - loop_len, n), resampling="linear", name=name)


def brr(wave: Wave) -> Wave:
    """Run a wave through SNES BRR compression (4-bit ADPCM in 16-sample blocks, filters 0-2) to
    get the S-DSP's characteristic grit. Loop points are moved to 16-sample block boundaries."""
    src = [int(max(-1.0, min(1.0, x)) * 32767) for x in wave.data]
    loop = None
    if wave.loop:
        start = (wave.loop[0] // 16) * 16
        length = max(16, ((wave.loop[1] - wave.loop[0]) // 16) * 16)
        src = src[:start + length]
        loop = (start, start + length)
    src += [0] * (-len(src) % 16)
    out, p1, p2 = [], 0, 0
    coeffs = [(0.0, 0.0), (15 / 16, 0.0), (61 / 32, -15 / 16)]
    for b in range(0, len(src), 16):
        block = src[b:b + 16]
        best = None
        for c1, c2 in coeffs:
            for shift in range(13):
                q1, q2, err, dec = p1, p2, 0, []
                step = 1 << shift
                for s in block:
                    pred = c1 * q1 + c2 * q2
                    nib = max(-8, min(7, int(round((s - pred) / step))))
                    v = int(max(-32768, min(32767, pred + nib * step)))
                    dec.append(v)
                    err += (v - s) ** 2
                    q2, q1 = q1, v
                if best is None or err < best[0]:
                    best = (err, dec, q1, q2)
        _, dec, p1, p2 = best
        out.extend(dec)
    return replace(wave, data=[v / 32768 for v in out], loop=loop, name=f"{wave.name} brr")
