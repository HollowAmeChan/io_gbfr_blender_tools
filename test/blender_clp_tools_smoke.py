"""Run with: blender --background --python this_file.py -- path/to/source/model.minfo"""

from pathlib import Path
import sys

import bpy


try:
    separator = sys.argv.index("--")
    minfo = Path(sys.argv[separator + 1]).resolve()
except (ValueError, IndexError):
    raise SystemExit("Pass a source workspace minfo after --")

bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
assert bpy.ops.gbfr.import_mesh(filepath=str(minfo), import_scale=1.0) == {"FINISHED"}

from io_gbfr_blender_tools.Entities.ModelSkeleton import ModelSkeleton
from io_gbfr_blender_tools.gbfr_cloth_blender import _export_bone_ids
from io_gbfr_blender_tools.gbfr_model_export_v2 import (
    appended_bone_export_name_map,
    rename_new_bones_for_experimental_export,
)
from io_gbfr_blender_tools.gbfr_session import active_session_armature
from io_gbfr_blender_tools.gbfr_workspace import resolve_model_export_targets


armature = active_session_armature(bpy.context)
assert armature is not None and armature.gbfr_cloth.enabled
state = armature.gbfr_cloth
targets = resolve_model_export_targets(state.workspace_path, state.model_id)
source_skeleton = ModelSkeleton.GetRootAs(bytearray(targets.reference_skeleton.read_bytes()), 0)

bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
parent = armature.data.edit_bones[6]
grid_names = []
for chain_name, x in (("CLP_TEST_A", -0.02), ("CLP_TEST_B", 0.0), ("CLP_TEST_C", 0.02)):
    previous = parent
    for depth in range(1, 3):
        bone = armature.data.edit_bones.new(f"{chain_name}_{depth:02d}")
        bone.head = (x, 0.02 * depth, 0.0)
        bone.tail = (x, 0.02 * depth + 0.015, 0.0)
        bone.parent = previous
        previous = bone
        grid_names.append(bone.name)

fork_names = []


def add_fork_bone(name, parent_bone, x, depth):
    bone = armature.data.edit_bones.new(name)
    bone.head = (x, 0.02 * depth, 0.03)
    bone.tail = (x, 0.02 * depth + 0.015, 0.03)
    bone.parent = parent_bone
    fork_names.append(bone.name)
    return bone


fork_01 = add_fork_bone("CLP_FORK_01", parent, 0.05, 1)
fork_02 = add_fork_bone("CLP_FORK_02", fork_01, 0.05, 2)
fork_03 = add_fork_bone("CLP_FORK_03", fork_02, 0.05, 3)
fork_a_04 = add_fork_bone("CLP_FORK_A_04", fork_03, 0.04, 4)
add_fork_bone("CLP_FORK_A_05", fork_a_04, 0.04, 5)
fork_b_04 = add_fork_bone("CLP_FORK_B_04", fork_03, 0.06, 4)
fork_b_05 = add_fork_bone("CLP_FORK_B_05", fork_b_04, 0.06, 5)
add_fork_bone("CLP_FORK_B_06", fork_b_05, 0.06, 6)
bpy.ops.object.mode_set(mode="OBJECT")

for bone in armature.data.bones:
    bone.select = bone.name in grid_names
mesh_objects = [value for value in armature.children_recursive if value.type == "MESH"]
expected_names = appended_bone_export_name_map(armature, mesh_objects, source_skeleton)
export_ids = _export_bone_ids(armature, state)
all_names = grid_names + fork_names
assert set(all_names) <= set(expected_names)
for name in all_names:
    assert export_ids[name] == int(expected_names[name][1:], 16)

state.active_clp_index = next(index for index, group in enumerate(state.clp_groups) if group.group_id == 2)
state.clp_tool_preset = "SKIRT"
state.clp_tool_topology = "GRID"
state.clp_tool_closed = False
state.clp_tool_apply_header = True
assert bpy.ops.gbfr.clp_create_from_selection(replace_existing=True) == {"FINISHED"}
group = state.clp_groups[state.active_clp_index]
assert len(group.nodes) == 6
by_bone = {node.bone: node for node in group.nodes}
a1, a2, b1, b2, c1, c2 = (export_ids[name] for name in grid_names)
assert by_bone[a1].down == a2 and by_bone[a2].up == a1
assert by_bone[b1].side == a1 and by_bone[b1].poly == a1
assert by_bone[b2].side == a2 and by_bone[b2].poly == a2
assert by_bone[c1].side == b1 and by_bone[c2].side == b2

state.clp_tool_closed = True
assert bpy.ops.gbfr.clp_rebuild_connections() == {"FINISHED"}
by_bone = {node.bone: node for node in group.nodes}
assert by_bone[a1].side == c1 and by_bone[a2].side == c2

for bone in armature.data.bones:
    bone.select = bone.name == grid_names[1]
assert bpy.ops.gbfr.clp_delete_selection(include_descendants=False) == {"FINISHED"}
by_bone = {node.bone: node for node in group.nodes}
assert a2 not in by_bone
assert by_bone[a1].down == 4095
assert by_bone[b2].side == 4095 and by_bone[b2].poly == 4095

for bone in armature.data.bones:
    bone.select = bone.name in fork_names
state.clp_tool_preset = "LONG_HAIR"
state.clp_tool_topology = "GRID"
try:
    bpy.ops.gbfr.clp_create_from_selection(replace_existing=True)
except RuntimeError as error:
    assert "分叉" in str(error)
else:
    raise AssertionError("grid topology unexpectedly accepted a fork")
state.clp_tool_topology = "CHAINS"
state.clp_tool_closed = False
assert bpy.ops.gbfr.clp_create_from_selection(replace_existing=True) == {"FINISHED"}
group = state.clp_groups[state.active_clp_index]
assert len(group.nodes) == 8
by_bone = {node.bone: node for node in group.nodes}
f1, f2, f3, fa4, fa5, fb4, fb5, fb6 = (export_ids[name] for name in fork_names)
assert by_bone[f1].down == f2 and by_bone[f2].down == f3
assert by_bone[f3].down == fb4 and by_bone[fb4].up == f3
assert by_bone[fa4].up == 4095 and by_bone[fa4].down == fa5
assert by_bone[fb4].down == fb5 and by_bone[fb5].down == fb6
assert all(node.side == 4095 and node.poly == 4095 for node in group.nodes)

rename_records = dict(rename_new_bones_for_experimental_export(armature, mesh_objects, source_skeleton))
assert rename_records == expected_names
for old_name, final_name in expected_names.items():
    assert armature.data.bones.get(final_name) is not None, (old_name, final_name)

print("GBFR CLP tools smoke passed")
