"""Run with: blender --background --python this_file.py -- path/to/model.minfo expected_count clip_name"""

from pathlib import Path
import sys

import bpy


separator = sys.argv.index("--")
minfo = Path(sys.argv[separator + 1]).resolve()
expected_count = int(sys.argv[separator + 2])
clip_name = sys.argv[separator + 3]
bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
assert bpy.ops.gbfr.import_mesh(filepath=str(minfo), import_scale=1.0) == {"FINISHED"}
armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
state = armature.gbfr_animation
assert state.enabled and len(state.animations) == expected_count
index = next(index for index, item in enumerate(state.animations) if item.display_name == clip_name)
state.active_animation_index = index
assert state.preview_active, "List selection did not load the MOT preview"
bpy.context.scene.frame_set(min(10, bpy.context.scene.frame_end))
delta = max(
    abs(pose_bone.matrix_basis[row][column] - (1.0 if row == column else 0.0))
    for pose_bone in armature.pose.bones for row in range(4) for column in range(4)
)
assert delta > 1e-5, delta
assert armature.animation_data is None or armature.animation_data.action is None
assert armature.animation_data is None or not armature.animation_data.nla_tracks
print(f"GBFR {state.model_id} animation smoke passed: {expected_count} indexed / {clip_name} delta {delta:.3g}")
