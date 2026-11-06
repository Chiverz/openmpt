"""Command line: ``python -m mptscript <command>``.

  run SCRIPT.py [--play]           run a composition script (it saves/renders itself)
  info SONG [--rows N] [--no-patterns]
                                   print the song as text (instruments, order, pattern grid)
  render SONG [OUT.wav] [--interpolation nearest|linear|cubic|sinc] [--amiga a500|a1200] [--repeat N] [--play]
  play FILE.wav|SONG               play a WAV (or render a module to a temp WAV and play it)
  letters FORMAT                   list effect / volume-column letters for it|xm|s3m|mod|mptm
"""

from __future__ import annotations

import argparse
import os
import runpy
import sys
import tempfile


def _cmd_run(args) -> int:
    script = os.path.abspath(args.script)
    sys.argv = [script] + args.args
    sys.path.insert(0, os.path.dirname(script))
    before = set()
    out_dir = os.path.dirname(script)
    try:
        before = {f for f in os.listdir(out_dir) if f.lower().endswith(".wav")}
    except OSError:
        pass
    runpy.run_path(script, run_name="__main__")
    if args.play:
        from .render import play
        wavs = sorted((f for f in os.listdir(out_dir) if f.lower().endswith(".wav")),
                      key=lambda f: os.path.getmtime(os.path.join(out_dir, f)), reverse=True)
        target = next((w for w in wavs if w not in before), wavs[0] if wavs else None)
        if target:
            print(f"playing {target}")
            play(os.path.join(out_dir, target))
    return 0


def _cmd_info(args) -> int:
    from .song import Song
    song = Song.load(args.song)
    print(song.describe(patterns=not args.no_patterns, max_rows=args.rows))
    return 0


def _cmd_render(args) -> int:
    from .render import play
    from .song import Song
    song = Song.load(args.song)
    out = args.out or os.path.splitext(args.song)[0] + ".wav"
    report = song.render(out, interpolation=args.interpolation, repeat=args.repeat, normalize=not args.no_normalize,
                         amiga=args.amiga)
    print(report)
    if args.play:
        play(out)
    return 0


def _cmd_play(args) -> int:
    from .render import play
    path = args.file
    if not path.lower().endswith(".wav"):
        from .song import Song
        song = Song.load(path)
        tmp = os.path.join(tempfile.gettempdir(), "mptscript_preview.wav")
        print(song.render(tmp))
        path = tmp
    play(path)
    return 0


def _cmd_letters(args) -> int:
    from .song import Song
    song = Song.new(args.format, channels=4)
    print(f"Effect column ({args.format}):")
    for letter, name in song.effect_letters().items():
        print(f"  {letter}xx  {name}")
    print(f"Volume column ({args.format}):")
    for letter, name in song.volume_letters().items():
        print(f"  {letter}xx  {name}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="mptscript", description="Script OpenMPT's sound engine from Python.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a composition script")
    r.add_argument("script")
    r.add_argument("args", nargs=argparse.REMAINDER)
    r.add_argument("--play", action="store_true", help="play the newest WAV the script wrote")
    r.set_defaults(func=_cmd_run)

    i = sub.add_parser("info", help="print a module as text")
    i.add_argument("song")
    i.add_argument("--rows", type=int, default=None, help="max rows per pattern to print")
    i.add_argument("--no-patterns", action="store_true")
    i.set_defaults(func=_cmd_info)

    d = sub.add_parser("render", help="render a module to WAV")
    d.add_argument("song")
    d.add_argument("out", nargs="?")
    d.add_argument("--interpolation", default="sinc", choices=["nearest", "linear", "cubic", "sinc"])
    d.add_argument("--repeat", type=int, default=0)
    d.add_argument("--no-normalize", action="store_true")
    d.add_argument("--amiga", choices=["a500", "a1200", "unfiltered"], default=None,
                   help="emulate Amiga Paula resampling/filter (MOD files)")
    d.add_argument("--play", action="store_true")
    d.set_defaults(func=_cmd_render)

    pl = sub.add_parser("play", help="play a WAV or module")
    pl.add_argument("file")
    pl.set_defaults(func=_cmd_play)

    lt = sub.add_parser("letters", help="list effect letters for a format")
    lt.add_argument("format", choices=["it", "mptm", "xm", "s3m", "mod"])
    lt.set_defaults(func=_cmd_letters)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
