"""Run with: blender --background --python this_file.py -- path/to/fp.minfo"""

from pathlib import Path
import sys

import bpy


separator = sys.argv.index("--")
minfo = Path(sys.argv[separator + 1]).resolve()
bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
assert bpy.ops.gbfr.import_mesh(filepath=str(minfo), import_scale=1.0) == {"FINISHED"}

from io_gbfr_blender_tools.bone_name_mappings import (
    BONE_NAME_MAPPINGS, FACE_DEFORM_GROUPS,
)
from io_gbfr_blender_tools.gbfr_session import active_session_armature
from io_gbfr_blender_tools.gbfr_animation_blender import _entry_action


armature = active_session_armature(bpy.context)
assert armature is not None
original_names = {
    bone.name for bone in armature.data.bones if bone.name.startswith("_8")
}
mapped_ids = {bone_name for group in FACE_DEFORM_GROUPS for bone_name in group}
assert original_names <= mapped_ids

mesh = next(
    obj for obj in bpy.context.scene.objects
    if obj.type == "MESH" and obj.vertex_groups.get("_830") is not None
)
assert bpy.ops.armature.translate_bones_to_unity_blender() == {"FINISHED"}
for original_name in original_names:
    editable_name = BONE_NAME_MAPPINGS[original_name][0]
    assert armature.data.bones.get(editable_name) is not None
    if editable_name.endswith(".L"):
        mirrored_name = editable_name[:-2] + ".R"
        assert bpy.utils.flip_name(editable_name) == mirrored_name
        assert armature.data.bones.get(mirrored_name) is not None
assert mesh.vertex_groups.get(BONE_NAME_MAPPINGS["_830"][0]) is not None

state = armature.gbfr_animation
animation_index = next(
    index for index, item in enumerate(state.animations)
    if item.display_name == "fp1400_e00a"
)
assert bpy.ops.gbfr.animation_import_action(
    animation_index=animation_index,
) == {"FINISHED"}
action = _entry_action(state.animations[animation_index])
assert action is not None
assert any("FaceDeform" in curve.data_path for curve in action.fcurves)

assert bpy.ops.armature.translate_bones_to_gbfr() == {"FINISHED"}
assert {
    bone.name for bone in armature.data.bones if bone.name.startswith("_8")
} == original_names
assert mesh.vertex_groups.get("_830") is not None
assert not any("FaceDeform" in curve.data_path for curve in action.fcurves)
assert any('pose.bones["_8' in curve.data_path for curve in action.fcurves)

print(
    f"GBFR face naming smoke passed: {len(original_names)} _8xx bones round-tripped"
)
