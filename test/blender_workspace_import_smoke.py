"""Run with: blender --background --python this_file.py -- path/to/model.minfo"""

from pathlib import Path
import sys

import bpy


try:
    separator = sys.argv.index("--")
    minfo = Path(sys.argv[separator + 1]).resolve()
except (ValueError, IndexError):
    raise SystemExit("Pass a workspace minfo after --")

bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
result = bpy.ops.gbfr.import_mesh(filepath=str(minfo), import_scale=1.0)
assert result == {"FINISHED"}, result
armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
assert len(armatures) == 1, len(armatures)
state = armatures[0].gbfr_cloth
assert state.enabled
assert len(state.clp_groups) > 0
assert len(state.clh_layers) > 0
assert Path(state.workspace_path).name == "workspace.json"
assert any("gbfr_bone_id" in bone for bone in armatures[0].data.bones)
meshes = [
    obj for obj in bpy.context.scene.objects
    if obj.type == "MESH" and "gbfr_material_json" in obj
]
assert len(meshes) == 1, len(meshes)
mesh = meshes[0]
assert mesh["gbfr_material_applied"] > 0
assert mesh["gbfr_material_missing"] == 0
assert Path(mesh["gbfr_material_json"]).name == "0.mmat.json"
for material in mesh.data.materials:
    node_types = {node.bl_idname for node in material.node_tree.nodes}
    assert {"ShaderNodeTexImage", "ShaderNodeEmission", "ShaderNodeBsdfTransparent", "ShaderNodeMixShader"} <= node_types
    assert material.surface_render_method == "BLENDED"
    texture_path = material.get("gbfr_albedo_dds") or material.get("gbfr_eye_conjunctiva_dds")
    assert texture_path and Path(texture_path).suffix.casefold() == ".dds"
from io_gbfr_blender_tools import gbfr_cloth_blender
batches = []
gbfr_cloth_blender._draw_armature(armatures[0], batches)
assert sum(len(lines) for lines, _color, _width in batches) > 0
sop = armatures[0].gbfr_sop
assert sop.enabled
assert len(sop.operations) == 101
assert sop.imported_constraint_count > 0
assert sop.preview_operation_count > 0
assert sop.unresolved_count == 63
constraints = [constraint for bone in armatures[0].pose.bones for constraint in bone.constraints if constraint.name.startswith("GBFR SOP ")]
assert len(constraints) == sop.imported_constraint_count
bpy.context.view_layer.update()
rest_error = max(
    abs(armatures[0].pose.bones[bone.name].matrix[row][column] - bone.matrix_local[row][column])
    for bone in armatures[0].data.bones for row in range(4) for column in range(4)
)
assert rest_error < 1e-4, rest_error
from io_gbfr_blender_tools import gbfr_animation_blender
animation = armatures[0].gbfr_animation
assert animation.enabled
assert len(animation.animations) == 524
animation.suspend_updates = True
animation.active_animation_index = 1
animation.suspend_updates = False
gbfr_animation_blender.load_selected_animation(armatures[0], bpy.context.scene)
assert animation.preview_active
assert armatures[0].animation_data is None or armatures[0].animation_data.action is None
assert armatures[0].animation_data is None or len(armatures[0].animation_data.nla_tracks) == 0
bpy.context.scene.frame_set(10)
motion_delta = max(
    abs(pose_bone.matrix_basis[row][column] - (1.0 if row == column else 0.0))
    for pose_bone in armatures[0].pose.bones for row in range(4) for column in range(4)
)
assert motion_delta > 1e-5, motion_delta
runtime = gbfr_animation_blender._ACTIVE_CLIPS[animation.cache_key]
local_error = None
for bone_id, tracks in runtime["tracks"].items():
    pose_bone = armatures[0].pose.bones[runtime["mapping"][bone_id]]
    if pose_bone.parent is None or pose_bone.constraints:
        continue
    expected = gbfr_animation_blender._sample_local_matrix(runtime["rest"][bone_id], tracks, 10.0)
    actual = pose_bone.parent.matrix.inverted_safe() @ pose_bone.matrix
    local_error = max(abs(actual[row][column] - expected[row][column]) for row in range(4) for column in range(4))
    break
assert local_error is not None and local_error < 1e-4, local_error
gbfr_animation_blender._stop_preview(armatures[0])
print(
    f"GBFR workspace import smoke passed: {len(state.clp_groups)} CLP / {len(state.clh_layers)} CLH / "
    f"{len(sop.operations)} SOP records / {sop.preview_operation_count} guarded operations / "
    f"{len(constraints)} approximate constraints / {sop.guarded_count} guard rejects / "
    f"{len(animation.animations)} indexed MOT / motion delta {motion_delta:.3g} / "
    f"local error {local_error:.2g} / rest error {rest_error:.2g}"
)
