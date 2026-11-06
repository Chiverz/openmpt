"""Render songs to WAV and report on the result.

The report gives an agent something to check without ears: duration, peak and
RMS level, clipping, and stretches of silence.
"""

from __future__ import annotations

import array
import math
import os
import sys
import wave
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Tuple, Union

if TYPE_CHECKING:  # pragma: no cover
    from .song import Song

INTERPOLATION = {"nearest": 0, "none": 0, "linear": 1, "cubic": 2, "sinc": 3}
AMIGA = {None: 0, "off": 0, "a500": 1, "a1200": 2, "unfiltered": 3}


def _db(x: float) -> float:
    return 20 * math.log10(x) if x > 0 else float("-inf")


@dataclass
class RenderReport:
    path: Optional[str]
    samplerate: int
    channels: int
    duration: float
    song_duration: float
    peak: float
    peak_db: float
    rms_db: float
    gain_db: float
    clipped_samples: int
    silent_spans: List[Tuple[float, float]] = field(default_factory=list)
    loudness_timeline: List[float] = field(default_factory=list)  # RMS dBFS per second

    @property
    def silent(self) -> bool:
        return self.peak < 1e-4

    def warnings(self) -> List[str]:
        w = []
        if self.silent:
            w.append("output is silent - check that patterns use valid instrument numbers and the order list is set")
        if self.clipped_samples:
            w.append(f"{self.clipped_samples} samples exceed full scale at unity gain (the WAV is normalised, but playback in "
                     "OpenMPT would clip) - lower song.sample_preamp or instrument/channel volumes")
        for a, b in self.silent_spans:
            w.append(f"silence from {a:.1f}s to {b:.1f}s")
        if self.duration < 0.5 and not self.silent:
            w.append("very short output - is the order list complete?")
        return w

    def __str__(self) -> str:
        lines = [
            f"Rendered {self.path or '(memory)'}: {self.duration:.2f}s, {self.samplerate} Hz, {self.channels} ch",
            f"  peak {self.peak_db:.1f} dBFS (after {self.gain_db:+.1f} dB normalisation), RMS {self.rms_db:.1f} dBFS",
            "  loudness per second (dBFS): " + " ".join(f"{v:.0f}" if v > -120 else "-inf" for v in self.loudness_timeline[:60])
            + (" ..." if len(self.loudness_timeline) > 60 else ""),
        ]
        for w in self.warnings():
            lines.append(f"  WARNING: {w}")
        return "\n".join(lines)


def render_pcm(song: "Song", samplerate: int = 44100, channels: int = 2, interpolation: str = "sinc",
               stereo_separation: int = 100, max_seconds: float = 600.0, repeat: int = 0,
               amiga: Optional[str] = None) -> array.array:
    """Render to an array of interleaved float32 samples."""
    if interpolation not in INTERPOLATION:
        raise ValueError(f"interpolation must be one of {sorted(INTERPOLATION)}")
    if amiga not in AMIGA:
        raise ValueError(f"amiga must be one of {[k for k in AMIGA if k]}")
    raw = song._m.render(samplerate, channels, INTERPOLATION[interpolation],
                         int(round(stereo_separation / 100 * 128)), float(max_seconds), int(repeat), AMIGA[amiga])
    pcm = array.array("f")
    pcm.frombytes(raw)
    return pcm


def render(song: "Song", path: Union[str, os.PathLike, None] = None, *, samplerate: int = 44100, channels: int = 2,
           interpolation: str = "sinc", stereo_separation: int = 100, normalize: bool = True,
           target_db: float = -1.0, max_seconds: float = 600.0, repeat: int = 0, bits: int = 16,
           amiga: Optional[str] = None) -> RenderReport:
    """Render the song (one pass through the order list) to a WAV file.

    interpolation: sample interpolation for instruments left on "default" resampling
      (nearest = gritty/authentic, sinc = smooth). Chip instruments made by
      ``add_instrument`` use their own setting (nearest for chip waves).
    stereo_separation: 0 (mono) .. 100 (normal) .. 200 (wide), percent.
    normalize: scale so the peak sits at `target_db` dBFS. The module itself is unchanged.
    repeat: extra loops of the song (0 = play once).
    bits: 16 (PCM) or 32 (float WAV).
    amiga: "a500", "a1200" or "unfiltered" emulates the Amiga's Paula chip (resampling and output
      filter) for MOD songs; overrides `interpolation` for them. None = off.
    """
    pcm = render_pcm(song, samplerate, channels, interpolation, stereo_separation, max_seconds, repeat, amiga)
    frames = len(pcm) // channels
    sec = samplerate * channels
    try:
        import numpy as np
    except ImportError:  # pure-Python fallback
        np = None

    if np is not None:
        a = np.frombuffer(pcm, dtype=np.float32).astype(np.float64)
        peak = float(np.max(np.abs(a))) if a.size else 0.0
        clipped = int(np.count_nonzero(np.abs(a) > 1.0))
        gain = (10 ** (target_db / 20)) / peak if normalize and peak > 1e-6 else 1.0
        a *= gain
        pad = (-a.size) % sec
        blocks = np.concatenate([a, np.zeros(pad)]).reshape(-1, sec) if a.size else np.zeros((0, sec))
        counts = np.full(len(blocks), sec, dtype=np.float64)
        if pad and len(counts):
            counts[-1] = sec - pad
        ms = (blocks ** 2).sum(axis=1) / np.maximum(counts, 1)
        timeline = [_db(math.sqrt(v)) for v in ms]
        rms = math.sqrt(float((a ** 2).mean())) if a.size else 0.0
        pcm = array.array("f", a.astype(np.float32).tobytes())
    else:
        peak = max((abs(x) for x in pcm), default=0.0)
        clipped = sum(1 for x in pcm if x > 1.0 or x < -1.0)
        gain = (10 ** (target_db / 20)) / peak if normalize and peak > 1e-6 else 1.0
        if gain != 1.0:
            for i in range(len(pcm)):
                pcm[i] *= gain
        total_sq = 0.0
        timeline = []
        for start in range(0, len(pcm), sec):
            chunk = pcm[start:start + sec]
            sq = sum(x * x for x in chunk)
            total_sq += sq
            timeline.append(_db(math.sqrt(sq / max(1, len(chunk)))))
        rms = math.sqrt(total_sq / max(1, len(pcm)))
    silent_spans = _silent_spans(timeline)

    if path is not None:
        path = os.fspath(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        _write_wav(path, pcm, samplerate, channels, bits)

    return RenderReport(
        path=path, samplerate=samplerate, channels=channels, duration=frames / samplerate,
        song_duration=song.duration, peak=min(1.0, peak * gain), peak_db=_db(peak * gain), rms_db=_db(rms),
        gain_db=_db(gain) if gain > 0 else 0.0, clipped_samples=clipped, silent_spans=silent_spans,
        loudness_timeline=timeline,
    )


def _silent_spans(timeline: List[float], threshold_db: float = -60.0, min_len: int = 2) -> List[Tuple[float, float]]:
    spans, start = [], None
    for i, v in enumerate(timeline):
        if v < threshold_db:
            if start is None:
                start = i
        elif start is not None:
            if i - start >= min_len:
                spans.append((float(start), float(i)))
            start = None
    if start is not None and len(timeline) - start >= min_len and start > 0:
        spans.append((float(start), float(len(timeline))))
    return spans


def _write_wav(path: str, pcm: array.array, samplerate: int, channels: int, bits: int) -> None:
    if bits == 16:
        try:
            import numpy as np
            ints = array.array("h", np.clip(np.round(np.frombuffer(pcm, dtype=np.float32) * 32767.0), -32768, 32767).astype(np.int16).tobytes())
        except ImportError:
            ints = array.array("h", (max(-32768, min(32767, int(round(x * 32767)))) for x in pcm))
        if sys.byteorder == "big":
            ints.byteswap()
        with wave.open(path, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(samplerate)
            w.writeframes(ints.tobytes())
    elif bits == 32:
        import struct
        out = array.array("f", pcm)
        if sys.byteorder == "big":
            out.byteswap()
        data = out.tobytes()
        fmt_chunk = struct.pack("<HHIIHH", 3, channels, samplerate, samplerate * channels * 4, channels * 4, 32)
        with open(path, "wb") as f:
            f.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt_chunk) + 8 + len(data)) + b"WAVE")
            f.write(b"fmt " + struct.pack("<I", len(fmt_chunk)) + fmt_chunk)
            f.write(b"data" + struct.pack("<I", len(data)) + data)
    else:
        raise ValueError("bits must be 16 or 32")


def play(path: Union[str, os.PathLike]) -> None:
    """Play a WAV file and block until it finishes (Windows: winsound; macOS: afplay; Linux: aplay/paplay)."""
    path = os.fspath(path)
    if sys.platform == "win32":
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME)
        return
    import shutil
    import subprocess
    for player in (["afplay"], ["paplay"], ["aplay", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
        if shutil.which(player[0]):
            subprocess.run(player + [path], check=False)
            return
    raise RuntimeError("no audio player found (tried afplay, paplay, aplay, ffplay)")
