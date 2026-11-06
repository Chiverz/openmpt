"""Human/agent-readable text dumps of a song.

The pattern grid uses the same cell syntax that ``Pattern.__setitem__`` and
``Song.parse_cell`` accept, so an agent can read a song, decide on changes and
write cells back verbatim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, List, Optional

from . import notes as N

if TYPE_CHECKING:  # pragma: no cover
    from .song import Pattern, Song

_EMPTY_CELL = "... .. ... ..."
_RES = {0: "nearest", 1: "linear", 2: "cubic", 3: "sinc", 4: "sinc", 5: "default"}
_NNA = {0: "cut", 1: "continue", 2: "off", 3: "fade"}


def pattern_text(pattern: "Pattern", rows: Optional[Iterable[int]] = None, channels: Optional[Iterable[int]] = None,
                 row_numbers: bool = True) -> str:
    song = pattern.song
    nch = song.num_channels
    chans = list(range(nch)) if channels is None else list(channels)
    data = song._m.pattern_get_data(pattern.index)
    rows = range(pattern.rows) if rows is None else rows
    rpb = max(1, song.rows_per_beat)
    lines: List[str] = []
    header = ("     " if row_numbers else "") + " | ".join(f"ch{c:<2} {_channel_label(song, c):<9.9}" for c in chans)
    lines.append(header)
    for r in rows:
        cells = []
        for c in chans:
            i = (r * nch + c) * 6
            from .song import Cell
            cell = Cell(*data[i:i + 6])
            cells.append(song.format_cell(cell) if not cell.empty else _EMPTY_CELL)
        prefix = f"{r:3d}{'*' if r % rpb == 0 else ' '} " if row_numbers else ""
        lines.append(prefix + " | ".join(cells))
    return "\n".join(lines)


def _channel_label(song: "Song", c: int) -> str:
    return song._m.channel_get(c)["name"] or ""


def describe(song: "Song", patterns: bool = True, max_rows: Optional[int] = None) -> str:
    m = song._m
    out: List[str] = []
    out.append(f"Song: {song.title!r}  format={song.format}  channels={song.num_channels}  "
               f"tempo={song.tempo}  speed={song.speed}  rows/beat={song.rows_per_beat}  "
               f"global_volume={song.global_volume}  preamp={song.sample_preamp}")
    if song.artist:
        out.append(f"Artist: {song.artist}")
    out.append(f"Duration: {song.duration:.2f}s")
    order = " ".join("---" if p == -1 else "+++" if p == -2 else str(p) for p in song.order)
    out.append(f"Order: {order}")
    out.append("")
    out.append("Channels:")
    for c in range(song.num_channels):
        d = m.channel_get(c)
        flags = (" MUTED" if d["mute"] else "") + (f" ->FX{d['plugin']}" if d.get("plugin") else "")
        out.append(f"  {c:2d} {d['name']!r:14} pan={d['pan']:3d} vol={d['volume']:2d}{flags}")
    out.append("")
    if m.num_instruments:
        out.append("Instruments (use these numbers in patterns):")
        for i in range(1, m.num_instruments + 1):
            d = m.instrument_get(i)
            smps = sorted(set(d["keyboard"]) - {0})
            env = d["volume_envelope"]
            env_s = "off"
            if env["enabled"]:
                env_s = " ".join(f"{t}:{v}" for t, v in env["points"])
                if env["sustain"]:
                    env_s += f" sus@{env['sustain'][0]}"
                if env["loop"]:
                    env_s += f" loop{env['loop']}"
            out.append(f"  {i:2d} {d['name']!r:18} samples={smps} fadeout={d['fadeout']} nna={_NNA.get(d['nna'])} "
                       f"resampling={_RES.get(d['resampling'], d['resampling'])} vol_env=[{env_s}]")
        out.append("")
    out.append("Samples:" if m.num_instruments else "Samples (use these numbers in patterns):")
    for i in range(1, m.num_samples + 1):
        d = m.sample_get(i)
        if d.get("opl"):
            from .opl import decode
            o = decode(d["opl"])
            mod, car = o["modulator"], o["carrier"]
            kind = "additive" if o["additive"] else "fm"
            out.append(f"  {i:2d} {d['name']!r:22} OPL FM vol={d['volume']} fb={o['feedback']} {kind} "
                       f"mod(mult={mod.mult} lvl={mod.level} wave={mod.wave}) car(mult={car.mult} lvl={car.level} wave={car.wave})")
            continue
        loop = f"loop={d['loop'][0]}-{d['loop'][1]}" if d["loop"] else "one-shot"
        out.append(f"  {i:2d} {d['name']!r:22} {d['length']:6d} frames {d['bits']}-bit c5={d['c5_speed']} "
                   f"vol={d['volume']} {loop}")
    out.append("")
    plugs = song.plugins
    if plugs:
        out.append("Plugins:")
        for slot, p in plugs.items():
            params = p["params"]
            ptxt = " ".join(f"{k}={v:.2f}" for k, v in params.items()) if isinstance(params, dict) else str(params)
            where = "(master) " if p["master"] else ""
            out.append(f"  FX{slot} {p.get('kind', p['library'])} {where}{ptxt}")
        out.append("")
    if patterns:
        used = [p for p in dict.fromkeys(song.order) if p >= 0]
        unused = [p.index for p in song.patterns if p.index not in used]
        for p in used + unused:
            pat = song.patterns[p]
            tag = "" if p in used else " (not in order list)"
            name = f" {pat.name!r}" if pat.name else ""
            out.append(f"Pattern {p}{name}: {pat.rows} rows{tag}")
            rows = range(pat.rows if max_rows is None else min(pat.rows, max_rows))
            out.append(pattern_text(pat, rows=rows))
            if max_rows is not None and pat.rows > max_rows:
                out.append(f"     ... {pat.rows - max_rows} more rows")
            out.append("")
    return "\n".join(out)
