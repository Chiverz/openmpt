"""OpenMPT's built-in effect plugins (portable DirectX DMO emulations plus OpenMPT's own).

They are stored in the module (it / mptm / xm) and run inside OpenMPT's mixer.

    slot = song.add_plugin("echo", wet_dry=0.35, feedback=0.4, left_delay=plugins.ms(250), right_delay=plugins.ms(375))
    song.channels[0].plugin = slot          # route a channel through it
    song.add_plugin("waves_reverb", master=True, reverb_mix=0.6)   # or apply to the whole mix

All parameters are normalised 0..1 like in OpenMPT's plugin editor. Helpers:
``ms(x)`` for DMO echo delays (1..2000 ms).
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple


def _magic_le(s: str) -> int:
    b = s.encode("ascii")
    return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)


DMO = 0x44584D4F  # 'DXMO'


class PluginType(NamedTuple):
    id1: int
    id2: int
    library: str
    params: List[str]
    doc: str


TYPES: Dict[str, PluginType] = {
    "chorus": PluginType(DMO, 0xEFE6629C, "{EFE6629C-81F7-4281-BD91-C9D604A95AF6}",
                         ["wet_dry", "depth", "frequency", "wave_shape", "phase", "feedback", "delay"], "DMO chorus"),
    "compressor": PluginType(DMO, 0xEF011F79, "{EF011F79-4000-406D-87AF-BFFB3FC39D57}",
                             ["gain", "attack", "release", "threshold", "ratio", "predelay"], "DMO compressor"),
    "distortion": PluginType(DMO, 0xEF114C90, "{EF114C90-CD1D-484E-96E5-09CFAF912A21}",
                             ["gain", "edge", "pre_lowpass_cutoff", "post_eq_center", "post_eq_bandwidth"], "DMO distortion"),
    "echo": PluginType(DMO, 0xEF3E932C, "{EF3E932C-D40B-4F51-8CCF-3F98F1B29D5D}",
                       ["wet_dry", "feedback", "left_delay", "right_delay", "pan_delay"],
                       "DMO stereo echo; delays 1..2000 ms (use plugins.ms()), pan_delay>=0.5 swaps sides each repeat"),
    "flanger": PluginType(DMO, 0xEFCA3D92, "{EFCA3D92-DFD8-4672-A603-7420894BAD98}",
                          ["wet_dry", "wave_shape", "frequency", "depth", "phase", "feedback", "delay"], "DMO flanger"),
    "gargle": PluginType(DMO, 0xDAFD8210, "{DAFD8210-5711-4B91-9FE3-F75B7AE279BF}",
                         ["rate", "wave_shape"], "DMO gargle (amplitude modulation)"),
    "i3dl2_reverb": PluginType(DMO, 0xEF985E71, "{EF985E71-D5C7-42D4-BA4D-2D073E2E96F4}",
                               ["room", "room_hf", "room_rolloff", "decay_time", "decay_hf_ratio", "reflections",
                                "reflections_delay", "reverb", "reverb_delay", "diffusion", "density", "hf_reference",
                                "quality"], "DMO I3DL2 environmental reverb"),
    "param_eq": PluginType(DMO, 0x120CED89, "{120CED89-3BF4-4173-A132-3CB406CF3231}",
                           ["center", "bandwidth", "gain"], "DMO parametric EQ band"),
    "waves_reverb": PluginType(DMO, 0x87FC0268, "{87FC0268-9A55-4360-95AA-004A1D9DE26C}",
                               ["in_gain", "reverb_mix", "reverb_time", "high_freq_rt_ratio"], "DMO Waves reverb"),
    "digibooster_echo": PluginType(_magic_le("DBM0"), _magic_le("Echo"), "DigiBooster Pro Echo",
                                   ["delay", "feedback", "mix", "cross"], "DigiBooster Pro echo DSP"),
    "symmod_echo": PluginType(_magic_le("SymM"), _magic_le("Echo"), "SymMOD Echo",
                              ["type", "delay", "feedback"], "Symphonie (SymMOD) echo"),
}


def ms(milliseconds: float) -> float:
    """DMO echo delay in milliseconds (1..2000) to the normalised parameter value."""
    return max(0.0, min(1.0, (milliseconds - 1.0) / 1999.0))


def resolve(kind: str) -> PluginType:
    key = kind.lower().replace(" ", "_").replace("-", "_")
    if key not in TYPES:
        raise ValueError(f"unknown plugin {kind!r}; available: {sorted(TYPES)}")
    return TYPES[key]
