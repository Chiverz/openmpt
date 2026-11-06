"""Chipset suite: one song per sound chip, plus unit tests for the chip-specific features they use.

Each example is run end to end into a temp dir, reloaded from disk and checked for format,
voice count, length, level/silence/clipping and (for a few voices) pitch.
"""

import math
import os
import subprocess
import sys

import numpy as np
import pytest

import mptscript as mpt
from mptscript import chip, compose, notes, opl, plugins

sys.path.insert(0, os.path.dirname(__file__))
from audiocheck import cents, fundamental, solo_pcm  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "examples")

# script, output module, format, voices, one-pass duration (s)
SUITE = [
    ("overworld_quest.py", "overworld_quest.it", "it", 4, 41.60),                       # Ricoh 2A03 (NES)
    ("arena_anthem.py", "arena_anthem.mod", "mod", 4, 69.12),                           # Amiga Paula
    ("chipsets/opl3_dos_shooter.py", "opl3_dos_shooter.mptm", "mptm", 8, 54.86),        # Yamaha OPL3
    ("chipsets/gameboy_korobeiniki.py", "gameboy_korobeiniki.it", "it", 4, 34.03),      # Game Boy APU
    ("chipsets/sid_c64_ninja.py", "sid_c64_ninja.it", "it", 3, 38.40),                  # MOS 6581 SID
    ("chipsets/ay_msx_infiltration.py", "ay_msx_infiltration.it", "it", 4, 44.30),      # AY-3-8910 / YM2149
    ("chipsets/ym2612_genesis_speed.py", "ym2612_genesis_speed.it", "it", 8, 32.00),    # YM2612 + SN76489
    ("chipsets/snes_spc700_platformer.py", "snes_spc700_platformer.it", "it", 8, 26.97),  # SPC700 / S-DSP
    ("chipsets/zx_beeper_mountain_king.py", "zx_beeper_mountain_king.it", "it", 1, 35.86),  # ZX beeper
]


@pytest.fixture(scope="module")
def suite_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("chipsets")
    env = dict(os.environ, MPTSCRIPT_OUT=str(out), PYTHONWARNINGS="error")
    for script, *_ in SUITE:
        r = subprocess.run([sys.executable, "-m", "mptscript", "run", os.path.join(EXAMPLES, script)], env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, f"{script} failed:\n{r.stdout}\n{r.stderr}"
        assert "WARNING" not in r.stdout, f"{script} render report has warnings:\n{r.stdout}"
    return out


@pytest.mark.parametrize("script,module,fmt,voices,duration", SUITE, ids=[s[0] for s in SUITE])
def test_chipset_song(suite_dir, script, module, fmt, voices, duration):
    song = mpt.Song.load(os.path.join(suite_dir, module))
    assert song.format == fmt
    assert song.num_channels == voices
    assert abs(song.duration - duration) < 0.05
    assert os.path.exists(os.path.join(suite_dir, os.path.splitext(module)[0] + ".wav"))
    # The song must loop: a second pass adds the looped section.
    assert song.order and song.order[-1] >= 0
    report = song.render(None, max_seconds=20)
    assert not report.silent and report.clipped_samples == 0 and not report.silent_spans
    for pat in song.patterns:
        for _, _, cell in pat.cells():
            assert cell.note in (0, notes.OFF, notes.CUT, notes.FADE) or notes.MIN <= cell.note <= notes.MAX
            if cell.note and notes.MIN <= cell.note <= notes.MAX:
                assert cell.instr, "note without instrument"


def test_committed_example_outputs_are_current(suite_dir):
    """The .it/.mod/.mptm files shipped next to the scripts must match what the scripts produce."""
    for script, module, *_ in SUITE:
        shipped = os.path.join(EXAMPLES, os.path.dirname(script), module)
        assert os.path.exists(shipped), f"missing shipped song {shipped}"
        with open(shipped, "rb") as a, open(os.path.join(suite_dir, module), "rb") as b:
            assert a.read() == b.read(), f"{shipped} is stale - re-run {script}"


# --- pitch checks on rendered songs ---------------------------------------------------------------

def test_beeper_melody_pitch(suite_dir):
    song = mpt.Song.load(os.path.join(suite_dir, "zx_beeper_mountain_king.it"))
    pcm, row = solo_pcm(song, 0, 3), 2.5 / 110 * 6
    for name, r in [("B-4", 0), ("C#5", 2), ("D-5", 4), ("E-5", 6), ("F#5", 8)]:
        assert abs(cents(fundamental(pcm, r * row + 0.005, row * 0.9, fmin=150), notes.frequency(name))) < 15


def test_fm_lead_pitch(suite_dir):
    song = mpt.Song.load(os.path.join(suite_dir, "ym2612_genesis_speed.it"))
    row = 2.5 / 150 * 6
    t = 64 * row
    pcm = solo_pcm(song, 1, t + 2)
    for name, r, d in [("A-5", 0, 2), ("D-6", 2, 3), ("F#6", 5, 3)]:
        assert abs(cents(fundamental(pcm, t + r * row + 0.01, d * row * 0.8), notes.frequency(name))) < 15


# --- OPL ---------------------------------------------------------------------------------------------

PURE_SINE = opl.patch(opl.Op(level=63), opl.Op(level=0, attack=15, decay=0, sustain_level=0))


@pytest.mark.parametrize("fmt", ["s3m", "mptm"])
@pytest.mark.parametrize("note", ["E-3", "C-5", "A-5", "C-7"])
def test_opl_tuning(fmt, note):
    song = mpt.Song.new(fmt, channels=2)
    song.add_opl_instrument("sine", PURE_SINE)
    song.patterns[0][0, 0] = f"{note} 01"
    f = fundamental(solo_pcm(song, 0, 1), 0.1, 0.8, fmax=4500)
    assert abs(cents(f, notes.frequency(note))) < 8


@pytest.mark.parametrize("fmt", ["s3m", "mptm"])
def test_opl_roundtrip(tmp_path, fmt):
    song = mpt.Song.new(fmt, channels=2)
    for name, p in opl.PRESETS.items():
        song.add_opl_instrument(name, p)
    path = song.save(tmp_path / f"o.{fmt}")
    loaded = mpt.Song.load(path)
    for i, (name, p) in enumerate(opl.PRESETS.items(), start=1):
        stored = loaded.samples[i].opl
        expected = list(p)
        if fmt == "s3m":  # OPL2 has only waveforms 0-3
            expected[8] &= 3
            expected[9] &= 3
        assert stored == expected, name
    assert "OPL FM" in loaded.describe(patterns=False)


def test_engine_warnings_become_python_warnings_once(tmp_path, capfd):
    """Regression: engine log messages used to be printed to stderr on every load/save."""
    song = mpt.Song.new("s3m", channels=12)
    i = song.add_opl_instrument("p", opl.PRESETS["organ"])
    for c in range(12):
        song.patterns[0][0, c] = mpt.Cell(notes.parse("C-5"), i)
    with pytest.warns(UserWarning, match="more than 9"):
        path = song.save(tmp_path / "many.s3m")
    import warnings as w
    with w.catch_warnings():
        w.simplefilter("error")
        song.save(path)          # same message again: reported only once per song
        mpt.Song.load(path).copy()  # copies save internally: must not re-report or print
    assert "more than 9" not in capfd.readouterr().err
    assert any("more than 9" in text for _, text in song.messages)


def test_message_on_format_without_comments_warns():
    with pytest.warns(UserWarning, match="cannot store a song message"):
        mpt.Song.new("s3m", channels=2).message = "lost"


@pytest.mark.parametrize("fmt", ["it", "mptm", "xm"])
def test_song_message_line_breaks_roundtrip(tmp_path, fmt):
    """Regression: '\\n' came back as '\\r' (IT/MPTM store CR line endings)."""
    song = mpt.Song.new(fmt, channels=2)
    song.message = "line one\nline two"
    assert song.message == "line one\nline two"
    assert mpt.Song.load(song.save(tmp_path / f"m.{fmt}")).message == "line one\nline two"


def test_opl_needs_s3m_or_mptm():
    with pytest.raises(ValueError):
        mpt.Song.new("it", channels=2).add_opl_instrument("x", opl.PRESETS["piano"])
    with pytest.raises(ValueError):
        opl.Op(level=64)
    assert opl.decode(opl.PRESETS["brass"])["feedback"] == 6
    assert opl.brighter(opl.PRESETS["piano"])[2] < opl.PRESETS["piano"][2]


# --- Plugins -----------------------------------------------------------------------------------

def _blip_song(fmt="it"):
    song = mpt.Song.new(fmt, channels=2)
    i = song.add_instrument("blip", chip.square(), envelope=chip.adsr(0, 2, 0, 1))
    song.patterns[0][0, 0] = mpt.Cell(notes.parse("C-5"), i)
    return song


@pytest.mark.parametrize("fmt", ["it", "mptm", "xm"])
def test_echo_plugin_roundtrip_and_audible(tmp_path, fmt):
    song = _blip_song(fmt)
    dry = np.frombuffer(mpt.render_pcm(song, max_seconds=2), dtype=np.float32)
    slot = song.add_plugin("echo", master=True, wet_dry=0.5, feedback=0.5, left_delay=plugins.ms(200), right_delay=plugins.ms(300))
    wet = np.frombuffer(mpt.render_pcm(song, max_seconds=2), dtype=np.float32)
    tail = slice(int(44100 * 0.5) * 2, None)
    assert np.abs(dry[tail]).max() < 1e-4 < np.abs(wet[tail]).max()
    loaded = mpt.Song.load(song.save(tmp_path / f"e.{fmt}"))
    info = loaded.plugin(slot)
    assert info["kind"] == "echo" and info["master"] and info["loaded"]
    assert abs(info["params"]["left_delay"] - plugins.ms(200)) < 1e-6
    again = np.frombuffer(mpt.render_pcm(loaded, max_seconds=2), dtype=np.float32)
    assert np.allclose(again, wet, atol=1e-4)


def test_every_builtin_plugin_loads():
    song = _blip_song()
    for slot, kind in enumerate(plugins.TYPES, start=1):
        assert song.add_plugin(kind, slot=slot) == slot
        assert song.plugin(slot)["kind"] == kind
        assert len(song.plugin(slot)["params"]) == len(plugins.TYPES[kind].params)
    assert set(k for k in (p.get("kind") for p in song.plugins.values())) == set(plugins.TYPES)
    with pytest.raises(ValueError):
        song.add_plugin("echo", bogus=1)
    with pytest.raises(ValueError):
        mpt.Song.new("s3m", channels=2).add_plugin("echo")


def test_channel_and_instrument_routing(tmp_path):
    song = _blip_song()
    slot = song.add_plugin("waves_reverb", reverb_mix=0.9)
    song.channels[0].plugin = slot
    loaded = mpt.Song.load(song.save(tmp_path / "r.it"))
    assert loaded.channels[0].plugin == slot
    song2 = _blip_song()
    s2 = song2.add_plugin("echo")
    song2.instruments[1].plugin = s2
    assert mpt.Song.load(song2.save(tmp_path / "r2.it")).instruments[1].plugin == s2


# --- Instrument filter --------------------------------------------------------------------------

def test_resonant_filter_roundtrip_and_effect(tmp_path):
    song = mpt.Song.new("it", channels=1)
    i = song.add_instrument("saw", chip.saw(length=64), filter=(40, 60))
    song.patterns[0][0, 0] = mpt.Cell(notes.parse("C-4"), i)
    loaded = mpt.Song.load(song.save(tmp_path / "f.it"))
    assert (loaded.instruments[i].filter_cutoff, loaded.instruments[i].filter_resonance) == (40, 60)

    def hf(s):
        x = solo_pcm(s, 0, 1)
        sp = np.abs(np.fft.rfft(x)) ** 2
        f = np.fft.rfftfreq(len(x), 1 / 44100)
        return sp[f > 2000].sum() / sp.sum()

    open_ = song.copy()
    open_.instruments[i].filter_cutoff = None
    assert hf(song) < hf(open_) / 5


# --- compose helpers ---------------------------------------------------------------------------------

def test_compose_line_and_voice():
    song = mpt.Song.new("it", channels=1, rows=48)
    song.rows_per_beat = 12
    end = compose.line(song.patterns[0], 0, [("C-5", compose.T), ("E-5", compose.T), ("G-5", compose.T), ("r", 1),
                                             ("C-6", 2)], 1, gap=1)
    assert end == 48
    p = song.patterns[0]
    assert [p[r, 0].note for r in (0, 4, 8)] == [notes.parse(n) for n in ("C-5", "E-5", "G-5")]
    assert p[12, 0].note == notes.OFF and p[24, 0].note == notes.parse("C-6") and p[47, 0].note == notes.CUT
    with pytest.raises(ValueError):
        compose.rows(0.1, 4)
    v = compose.Voice(3, play="F-5", root="E-3", low="C-4", high="B-6")
    assert v.note("E-3") == notes.parse("F-5") and int(v) == 3
    with pytest.raises(ValueError):
        v.note("E-5")


# --- chip generators -----------------------------------------------------------------------------

def test_fm_voice_tuned_and_loops():
    w = chip.fm([chip.FMOp(1, 1.0, decay=0.1, sustain=0.3), chip.FMOp(1, 1.0), chip.FMOp(2, 0.5), chip.FMOp(1, 0.8)],
                algorithm=4, root="A-4", duration=0.8)
    s, e = w.loop
    period = (e - s) // 24
    assert (e - s) % period == 0
    # the loop is a whole number of periods: the sample after the loop end continues the waveform
    assert abs(w.data[s] - w.data[s - period]) < 0.05
    song = mpt.Song.new("it", channels=1)
    i = song.add_instrument("fm", w)
    song.patterns[0][0, 0] = mpt.Cell(notes.parse("A-4"), i)
    assert abs(cents(fundamental(solo_pcm(song, 0, 1), 0.3, 0.6, fmin=100), notes.frequency("A-4"))) < 10
    for alg in chip.FM_ALGORITHMS:
        assert chip.fm([chip.FMOp()] * 4, algorithm=alg, duration=0.1).data


def test_pwm_brr_ay():
    p = chip.pwm(cycles=32, period=64)
    assert len(p.data) == 32 * 64 and p.loop == (0, 32 * 64)
    duties = {sum(1 for x in p.data[k * 64:(k + 1) * 64] if x > 0) for k in range(32)}
    assert len(duties) > 8  # the pulse width really moves
    b = chip.brr(chip.sine(64))
    assert b.loop[0] % 16 == 0 and (b.loop[1] - b.loop[0]) % 16 == 0
    assert max(abs(x - y) for x, y in zip(b.data, chip.sine(64).data)) < 0.05
    assert len({round(x, 6) for x in chip.ay_buzzer("saw", steps=32).data}) == 32
    for kind in ("kick", "snare", "tom"):
        d = chip.sid_drum(kind).data
        assert d and max(abs(x) for x in d) <= 1.0
