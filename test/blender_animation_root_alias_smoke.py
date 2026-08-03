"""Run with: blender --background --factory-startup --python this_file.py"""

from pathlib import Path

import bpy


bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")

from io_gbfr_blender_tools.gbfr_animation import (
    AnimationClip,
    AnimationKey,
    AnimationTrack,
)
from io_gbfr_blender_tools.gbfr_animation_blender import _track_binding_layout


def track(bone_id, prop=0):
    return AnimationTrack(
        bone_id, prop, 0, 0, "constant", (AnimationKey(0, 0.0),),
    )


def runtime(*tracks):
    clip = AnimationClip(Path("root_alias.mot"), 1, 0, 1, 0, "root_alias", tracks)
    return {
        "clip": clip,
        "mapping": {0x900: "Root"},
        "rest": {0x900: object()},
    }


layout = _track_binding_layout(runtime(track(-1), track(0x900)))
assert layout[0] == (0x900, 0, False, "被后续根轨道覆盖")
assert layout[1] == (0x900, 0, True, None)

layout = _track_binding_layout(runtime(track(0x900), track(-1)))
assert layout[0] == (0x900, 0, False, "被后续根轨道覆盖")
assert layout[1] == (0x900, 0, True, None)

try:
    _track_binding_layout(runtime(track(0x900), track(0x900)))
except ValueError as error:
    assert "重复骨 2304 属性 0" in str(error)
else:
    raise AssertionError("A real duplicate root track must still be rejected")

print("GBFR animation root alias smoke passed")
