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
bone_by_id = {int(bone["gbfr_bone_id"]): bone.name for bone in armatures[0].data.bones}
for group in state.clp_groups:
    for node in group.nodes:
        assert node.bone_ref == bone_by_id[node.bone]
        for raw_attr in ("up", "down", "side", "poly", "fix"):
            raw_value = getattr(node, raw_attr)
            reference = getattr(node, raw_attr + "_ref")
            assert reference == ("" if raw_value == 4095 else bone_by_id[raw_value])
for layer in state.clh_layers:
    by_collision_id = {value.collision_id: value for value in layer.collisions}
    for value in layer.collisions:
        assert value.p1_ref == bone_by_id[value.p1]
        assert value.p2_ref == bone_by_id[value.p2]
        target = by_collision_id.get(value.capsule)
        assert value.capsule_ref == (target.name if target else "")

editable_node = next(node for group in state.clp_groups for node in group.nodes if node.down != 4095)
old_down, old_down_ref = editable_node.down, editable_node.down_ref
editable_node.down_ref = editable_node.bone_ref
assert editable_node.down == editable_node.bone
editable_node.suspend_reference_updates = True
editable_node.down = old_down
editable_node.down_ref = old_down_ref
editable_node.suspend_reference_updates = False

editable_collision = next(value for layer in state.clh_layers for value in layer.collisions)
old_p1, old_p1_ref = editable_collision.p1, editable_collision.p1_ref
editable_collision.p1_ref = editable_collision.p2_ref
assert editable_collision.p1 == editable_collision.p2
editable_collision.p1_ref = old_p1_ref
assert editable_collision.p1 == old_p1

capsule_layer = next(layer for layer in state.clh_layers if len(layer.collisions) > 1)
capsule_value = capsule_layer.collisions[0]
capsule_target = capsule_layer.collisions[1]
old_capsule, old_capsule_ref = capsule_value.capsule, capsule_value.capsule_ref
capsule_value.capsule_ref = capsule_target.name
assert capsule_value.capsule == capsule_target.collision_id
capsule_value.suspend_reference_updates = True
capsule_value.capsule = old_capsule
capsule_value.capsule_ref = old_capsule_ref
capsule_value.suspend_reference_updates = False

bpy.context.view_layer.objects.active = armatures[0]
bpy.ops.gbfr.select_bone_reference(bone_name=editable_node.bone_ref)
assert armatures[0].data.bones.active.name == editable_node.bone_ref
layer_id = next(layer.group_id for layer in state.clh_layers if 0 <= layer.group_id < 31)
mask_attr = "header_useCollisionFlags"
old_mask = getattr(state.clp_groups[state.active_clp_index], mask_attr)
bpy.ops.gbfr.toggle_collision_layer(layer_id=layer_id)
assert getattr(state.clp_groups[state.active_clp_index], mask_attr) == old_mask ^ (1 << layer_id)
bpy.ops.gbfr.toggle_collision_layer(layer_id=layer_id)
assert getattr(state.clp_groups[state.active_clp_index], mask_attr) == old_mask
from io_gbfr_blender_tools.gbfr_cloth_blender import GBFRClpGroupProperties
assert GBFRClpGroupProperties.bl_rna.properties["header_airResistance"].name == "空气阻力"
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
