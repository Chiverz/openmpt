import math
import os
import subprocess
import sys
import wave

import pytest

import mptscript as mpt
from mptscript import chip, fx, notes

FORMATS = ["it", "mptm", "xm", "s3m", "mod"]


def small_song(fmt, channels=4):
    song = mpt.Song.new(fmt, channels=channels, title=f"t-{fmt}", tempo=125, speed=6)
    a = song.add_instrument("sq", chip.square())
    b = song.add_instrument("tri", chip.triangle())
    p = song.patterns[0]
    p.write(0, "C-5 . E-5 . G-5 . ===", instrument=a, step=2)
    p.write(1, "C-3 . . . G-2", instrument=b, step=4)
    p.set(8, 0, "C-6", a, effect=fx.arpeggio(3, 7))
    return song


# --- notes -----------------------------------------------------------------------

def test_note_parsing_roundtrip():
    assert notes.parse("C-5") == notes.MIDDLE_C == 61
    assert notes.parse("C5") == 61
    assert notes.parse("C#4") == notes.parse("Db4") == 50
    assert notes.parse("===") == notes.OFF and notes.parse("off") == notes.OFF
    assert notes.parse("^^^") == notes.CUT
    assert notes.parse("...") == notes.parse(None) == 0
    for n in range(notes.MIN, notes.MAX + 1):
        assert notes.parse(notes.name(n)) == n
    assert notes.from_midi(60) == 61
    assert abs(notes.frequency("A-5") - 440.0) < 1e-9
    assert notes.chord("C-4", "min") == ["C-4", "D#4", "G-4"]
    with pytest.raises(ValueError):
        notes.parse("H-5")


# --- format round trips ------------------------------------------------------------

@pytest.mark.parametrize("fmt", FORMATS)
def test_save_load_roundtrip(tmp_path, fmt):
    song = small_song(fmt)
    path = song.save(tmp_path / f"song.{fmt}")
    loaded = mpt.Song.load(path)
    assert loaded.format == fmt
    assert loaded.title == f"t-{fmt}"
    assert loaded.order[:1] == [0]
    assert loaded.num_channels == song.num_channels
    for r in range(song.patterns[0].rows):
        for c in range(2):
            assert loaded.patterns[0][r, c] == song.patterns[0][r, c], (fmt, r, c)
    assert loaded.samples[1].loop == (0, 32)
    if fmt != "mod":  # MOD stores 8-bit samples
        a, b = song.samples[1].data, loaded.samples[1].data
        assert len(a) == len(b) and max(abs(x - y) for x, y in zip(a, b)) < 1e-3


def test_note_off_adapted_to_format():
    s3m = small_song("s3m")
    assert s3m.patterns[0][12, 0].note == notes.CUT
    mod = small_song("mod")
    assert mod.patterns[0][12, 0].note == 0
    assert mod.patterns[0][12, 0].astuple()[4:] == (mpt.EFFECTS["MODCMDEX"], 0xC0)
    mod.patterns[0].set(20, 1, "^^^")  # set() must adapt too
    assert mod.patterns[0][20, 1].astuple() == (0, 0, 0, 0, mpt.EFFECTS["MODCMDEX"], 0xC0)


@pytest.mark.parametrize("fmt", ["it", "xm", "mptm"])
def test_instrument_envelope_roundtrip(tmp_path, fmt):
    song = mpt.Song.new(fmt, channels=2)
    env = chip.adsr(attack=2, decay=6, sustain=30, release=10)
    i = song.add_instrument("lead", chip.pulse(0.25), envelope=env, resampling="nearest")
    path = song.save(tmp_path / f"e.{fmt}")
    ins = mpt.Song.load(path).instruments[i]
    venv = ins.volume_envelope
    assert venv["enabled"]
    assert [tuple(p) for p in venv["points"]] == env["points"]
    assert tuple(venv["sustain"]) == env["sustain"]
    assert ins.name == "lead"


def test_mod_has_no_instruments_warns():
    song = mpt.Song.new("mod", channels=4)
    with pytest.warns(UserWarning):
        idx = song.add_instrument("x", chip.square(), envelope=chip.adsr())
    assert idx == 1 and song._m.num_instruments == 0


def test_format_mismatch_raises(tmp_path):
    song = mpt.Song.new("xm", channels=2)
    with pytest.raises(ValueError):
        song._m.save(str(tmp_path / "x.it"), "it")


# --- cell text syntax ------------------------------------------------------------------

@pytest.mark.parametrize("fmt", ["it", "xm", "s3m"])
def test_cell_text_roundtrip(fmt):
    song = small_song(fmt)
    for r, c, cell in song.patterns[0].cells():
        text = song.format_cell(cell)
        assert song.parse_cell(text) == cell, text


def test_cell_text_variants():
    song = mpt.Song.new("it", channels=2)
    c = song.parse_cell("C-5 01 v48 J37")
    assert (c.note, c.instr, c.volcmd, c.vol, c.command, c.param) == (61, 1, mpt.VOLCMDS["VOLUME"], 48, mpt.EFFECTS["ARPEGGIO"], 0x37)
    assert song.parse_cell("C-5 01") == mpt.Cell(61, 1)
    assert song.parse_cell("... .. ... A03").command == mpt.EFFECTS["SPEED"]
    assert song.parse_cell("===").note == notes.OFF
    xm = mpt.Song.new("xm", channels=2)
    assert xm.parse_cell("C-5 01 ... 037").command == mpt.EFFECTS["ARPEGGIO"]
    assert xm.parse_cell("F80").command == mpt.EFFECTS["TEMPO"]
    assert xm.parse_cell("F06").command == mpt.EFFECTS["SPEED"]
    with pytest.raises(ValueError):
        song.parse_cell("C-5 01 v48 ?37")


def test_format_aware_effects():
    it = mpt.Song.new("it", channels=1)
    xm = mpt.Song.new("xm", channels=1)
    mod = mpt.Song.new("mod", channels=4)
    assert it.make_cell(effect=fx.note_cut(3)).command == mpt.EFFECTS["S3MCMDEX"]
    assert xm.make_cell(effect=fx.note_cut(3)).command == mpt.EFFECTS["MODCMDEX"]
    assert it.make_cell(effect=fx.note_cut(3)).param == xm.make_cell(effect=fx.note_cut(3)).param == 0xC3
    assert mod.make_cell(effect=fx.retrig(3)).astuple()[4:] == (mpt.EFFECTS["MODCMDEX"], 0x93)
    # Volume goes to the volume column where possible, otherwise to Cxx.
    assert it.make_cell("C-5", 1, volume=32).volcmd == mpt.VOLCMDS["VOLUME"]
    assert mod.make_cell("C-5", 1, volume=32).command == mpt.EFFECTS["VOLUME"]


# --- editing ---------------------------------------------------------------------------

def test_channel_count_change_preserves_data():
    song = small_song("it", channels=4)
    before = [song.patterns[0][r, c] for r in range(16) for c in range(4)]
    song.num_channels = 6
    assert [song.patterns[0][r, c] for r in range(16) for c in range(4)] == before
    assert song.patterns[0][0, 5].empty
    song.num_channels = 2
    assert song.patterns[0][0, 0].note == notes.parse("C-5")


def test_pattern_helpers():
    song = small_song("it")
    p = song.patterns[0]
    p.transpose(12, channels=[0])
    assert p[0, 0].note == notes.parse("C-6")
    assert p[12, 0].note == notes.OFF  # note-offs untouched
    q = song.add_pattern(32, name="b")
    q.copy_from(p, channels=[0], dest_channels=[2])
    assert q[0, 2].note == notes.parse("C-6")
    q.drums(3, "x.X.o.r.", 1)
    assert q[0, 3].note and q[2, 3].vol == 64 and q[4, 3].vol == 24
    assert q[6, 3].command == mpt.EFFECTS["RETRIG"]
    song.order = [0, q.index, 0]
    assert song.order == [0, q.index, 0]
    with pytest.raises(ValueError):
        song.order = [0, 99]
    with pytest.raises(ValueError):
        p.write(0, " ".join(["C-5"] * 65))


# --- rendering -------------------------------------------------------------------------

def test_render_duration_and_levels(tmp_path):
    song = small_song("it")
    # classic tempo: 2.5 / tempo seconds per tick -> 64 rows * 6 ticks * 0.02 s = 7.68 s
    assert abs(song.duration - 7.68) < 1e-6
    report = song.render(tmp_path / "x.wav")
    assert abs(report.duration - 7.68) < 0.05
    assert not report.silent
    assert -1.5 < report.peak_db <= -0.9
    with wave.open(str(tmp_path / "x.wav")) as w:
        assert w.getnchannels() == 2 and w.getframerate() == 44100
        assert abs(w.getnframes() / 44100 - 7.68) < 0.05


def test_render_deterministic():
    song = small_song("xm")
    a = mpt.render_pcm(song)
    b = mpt.render_pcm(song)
    assert a == b and len(a) > 0


def test_silent_song_is_flagged():
    song = mpt.Song.new("it", channels=2)
    report = song.render(None)
    assert report.silent
    assert any("silent" in w for w in report.warnings())


def test_tempo_changes_duration():
    song = small_song("it")
    d1 = song.duration
    song.tempo = 250
    assert abs(song.duration - d1 / 2) < 0.01


# --- chip synthesis ------------------------------------------------------------------

def test_chip_waves_are_tuned_and_bounded():
    for w in [chip.pulse(0.125), chip.square(), chip.triangle(), chip.saw(), chip.sine(), chip.noise(), chip.noise(True),
              chip.kick(), chip.snare(), chip.hihat(), chip.hihat(open=True), chip.tom(), chip.crash()]:
        assert w.data and all(-1.0 <= x <= 1.0 for x in w.data), w.name
    sq = chip.square(length=32)
    assert sq.loop == (0, 32)
    assert abs(sq.c5_speed / 32 - chip.MIDDLE_C_HZ) < 1.0
    tri = chip.triangle(steps=16)
    assert len(set(round(x, 6) for x in tri.data)) <= 16
    assert len(chip.bitcrush(chip.sine(), 2).data) == 64


def test_adsr_shape():
    env = chip.adsr(attack=4, decay=6, sustain=32, release=8)
    assert env["points"] == [(0, 0), (4, 64), (10, 32), (18, 0)]
    assert env["sustain"] == (2, 2)
    with pytest.raises(ValueError):
        chip.envelope([(0, 64), (0, 10)])


def test_describe_mentions_everything():
    song = small_song("it")
    text = song.describe()
    assert "Instruments" in text and "'sq'" in text and "Pattern 0" in text and "C-6 01 ... J37" in text


# --- CLI / examples ----------------------------------------------------------------------

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "examples")


def test_examples_run(tmp_path):
    env = dict(os.environ, MPTSCRIPT_OUT=str(tmp_path))
    subprocess.run([sys.executable, "-m", "mptscript", "run", os.path.join(EXAMPLES, "chip_demo.py")], check=True, env=env,
                   capture_output=True)
    out = str(tmp_path)
    assert os.path.exists(os.path.join(out, "chip_demo.it"))
    subprocess.run([sys.executable, "-m", "mptscript", "run", os.path.join(EXAMPLES, "edit_existing.py")], check=True,
                   env=env, capture_output=True)
    v2 = mpt.Song.load(os.path.join(out, "chip_demo_v2.it"))
    assert v2.num_channels == 7 and v2.tempo == 165
    r = subprocess.run([sys.executable, "-m", "mptscript", "info", os.path.join(out, "chip_demo_v2.it"), "--rows", "4"],
                       check=True, capture_output=True, text=True)
    assert "Echo" in r.stdout
    subprocess.run([sys.executable, os.path.join(EXAMPLES, "minimal.py")], check=True, cwd=tmp_path, capture_output=True)
    subprocess.run([sys.executable, "-m", "mptscript", "run", os.path.join(EXAMPLES, "overworld_quest.py")], check=True,
                   env=env, capture_output=True)
    quest = mpt.Song.load(os.path.join(out, "overworld_quest.it"))
    assert abs(quest.duration - 41.6) < 0.01  # intro + one pass of the loop (position jump back to order 1)
    subprocess.run([sys.executable, "-m", "mptscript", "run", os.path.join(EXAMPLES, "arena_anthem.py")], check=True,
                   env=env, capture_output=True)
    anthem = mpt.Song.load(os.path.join(out, "arena_anthem.mod"))
    assert anthem.format == "mod" and anthem.num_channels == 4 and abs(anthem.duration - 69.12) < 0.01
    assert (tmp_path / "minimal.wav").exists()


def test_amiga_emulation_changes_mod_render():
    song = small_song("mod")
    assert mpt.render_pcm(song, max_seconds=2, amiga="a500") != mpt.render_pcm(song, max_seconds=2)
    with pytest.raises(ValueError):
        mpt.render_pcm(song, amiga="c64")
