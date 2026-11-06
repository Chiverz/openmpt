"""Helpers for checking rendered audio in tests (pitch by FFT, per-channel solo renders)."""

import numpy as np

import mptscript as mpt

SR = 44100


def solo_pcm(song, channel, seconds, **kw):
    """Mono render of one channel only (works on a copy, so the song is untouched)."""
    s = song.copy()
    for c in range(s.num_channels):
        s.channels[c].mute = c != channel
    for slot in list(s.plugins):
        s._m.plugin_remove(slot)
    return np.frombuffer(mpt.render_pcm(s, channels=1, max_seconds=seconds, **kw), dtype=np.float32)


def pitch(pcm, t0, dur, fmin=30.0, fmax=4000.0):
    """Strongest spectral peak (Hz) in pcm[t0 : t0 + dur] seconds, zero-padded for resolution."""
    seg = pcm[int(t0 * SR):int((t0 + dur) * SR)].astype(np.float64)
    seg = seg * np.hanning(len(seg))
    n = 16 * len(seg)
    spec = np.abs(np.fft.rfft(seg, n))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    mask = (freqs > fmin) & (freqs < fmax)
    return float(freqs[mask][np.argmax(spec[mask])])


def fundamental(pcm, t0, dur, fmin=30.0, fmax=2500.0, harmonics=4):
    """Fundamental frequency via harmonic product spectrum: robust for bright, harmonic-rich tones
    (FM, pulse, saw) where the loudest peak is often an overtone."""
    seg = pcm[int(t0 * SR):int((t0 + dur) * SR)].astype(np.float64)
    seg = seg * np.hanning(len(seg))
    n = 16 * len(seg)
    spec = np.abs(np.fft.rfft(seg, n))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    hps = spec.copy()
    for h in range(2, harmonics + 1):
        dec = spec[::h]
        hps[:len(dec)] *= dec
        hps[len(dec):] = 0
    mask = (freqs > fmin) & (freqs < fmax)
    coarse = float(freqs[mask][np.argmax(hps[mask])])
    # refine on the plain spectrum near the HPS estimate
    near = (freqs > coarse * 0.97) & (freqs < coarse * 1.03)
    return float(freqs[near][np.argmax(spec[near])])


def cents(f, ref):
    return 1200 * np.log2(f / ref)
