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
from io_gbfr_blender_tools.gbfr_bone_selection import selected_bone_names
from io_gbfr_blender_tools.gbfr_cloth_blender import _export_bone_ids
from io_gbfr_blender_tools.gbfr_cloth_format import ClpNode, MISSING_BONE
from io_gbfr_blender_tools.gbfr_model_export_v2 import (
    appended_bone_export_name_map,
    rename_new_bones_for_experimental_export,
)
from io_gbfr_blender_tools.gbfr_session import active_session_armature
from io_gbfr_blender_tools.gbfr_workspace import resolve_model_export_targets


armature = active_session_armature(bpy.context)
assert armature is not None and armature.gbfr_cloth.enabled
state = armature.gbfr_cloth
create_rna = bpy.ops.gbfr.clp_create_from_selection.get_rna_type()
assert create_rna.properties["apply_header"].default is False
assert create_rna.properties["apply_header"].name == "覆盖物理参数"
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
for bone in armature.data.edit_bones:
    bone.select = bone.select_head = bone.select_tail = bone.name in grid_names
assert set(selected_bone_names(bpy.context, armature)) == set(grid_names)
bpy.ops.object.mode_set(mode="OBJECT")

for bone in armature.data.bones:
    bone.select = bone.name in grid_names
mesh_objects = [value for value in armature.children_recursive if value.type == "MESH"]
all_names = grid_names + fork_names
unreserved_names = appended_bone_export_name_map(armature, mesh_objects, source_skeleton)
reserved_name = unreserved_names[grid_names[0]]
reserved_id = int(reserved_name[1:], 16)
other_group = next(group for group in state.clp_groups if group.group_id != 2 and group.nodes)
other_node = other_group.nodes[0]
other_node.fix = reserved_id
other_layer = next(layer for layer in state.clh_layers if layer.collisions)
other_collision = other_layer.collisions[0]
other_collision.p1 = reserved_id
export_ids = _export_bone_ids(armature, state, persist_appended=True)
assert reserved_id not in export_ids.values()
expected_names = appended_bone_export_name_map(armature, mesh_objects, source_skeleton)
assert set(all_names) <= set(expected_names)
for name in all_names:
    assert export_ids[name] == int(expected_names[name][1:], 16)
    assert int(armature.data.bones[name]["gbfr_bone_id"]) == export_ids[name]

state.active_clp_index = next(index for index, group in enumerate(state.clp_groups) if group.group_id == 2)
group = state.clp_groups[state.active_clp_index]
new_ids = {export_ids[name] for name in grid_names}
first_chain_names = grid_names[:2]
remaining_chain_names = grid_names[2:]
first_chain_ids = {export_ids[name] for name in first_chain_names}
activated_source_id = group.nodes[0].bone
group.nodes[0].side = min(first_chain_ids)
group.nodes[0].fix = min(first_chain_ids)
node_fields = tuple(ClpNode.__dataclass_fields__)
side_index = node_fields.index("side")
fix_index = node_fields.index("fix")


def node_snapshot(node):
    values = []
    for field in node_fields:
        value = getattr(node, field)
        values.append(tuple(value) if field == "offset" else value)
    return tuple(values)


original_nodes = {node.bone: node_snapshot(node) for node in group.nodes}
for bone in armature.data.bones:
    bone.select = bone.name in first_chain_names
assert bpy.ops.gbfr.clp_create_from_selection(
    replace_existing=False,
    preset_key="SHORT_HAIR",
    topology="CHAINS",
    closed=False,
    apply_header=False,
) == {"FINISHED"}
assert len(group.nodes) == len(original_nodes) + len(first_chain_names)
after_first_add = {node.bone: node_snapshot(node) for node in group.nodes}
for name in first_chain_names:
    bone = armature.data.bones[name]
    bone["gbfr_bone_id"] = -1
    bone["gbfr_original_name"] = bone.name
    bone["original_name"] = bone.name
for bone in armature.data.bones:
    bone.select = bone.name in remaining_chain_names
assert bpy.ops.gbfr.clp_create_from_selection(
    replace_existing=False,
    preset_key="SHORT_HAIR",
    topology="CHAINS",
    closed=False,
    apply_header=False,
) == {"FINISHED"}
assert len(group.nodes) == len(original_nodes) + len(grid_names)
after_add = {node.bone: node for node in group.nodes}
for bone_id, before in original_nodes.items():
    after = node_snapshot(after_add[bone_id])
    if bone_id == activated_source_id:
        assert after[side_index] == MISSING_BONE
        assert after[fix_index] == MISSING_BONE
        ignored = {side_index, fix_index}
        assert tuple(value for index, value in enumerate(after) if index not in ignored) == tuple(
            value for index, value in enumerate(before) if index not in ignored
        )
    else:
        assert after == before
for bone_id in first_chain_ids:
    assert node_snapshot(after_add[bone_id]) == after_first_add[bone_id]
for name in first_chain_names:
    assert int(armature.data.bones[name]["gbfr_bone_id"]) == export_ids[name]
assert "迁移" in state.last_status
assert other_node.fix == reserved_id
assert other_collision.p1 == reserved_id
for bone_id in new_ids:
    node = after_add[bone_id]
    for field in ("up", "down", "side", "poly", "fix"):
        target = getattr(node, field)
        assert target == MISSING_BONE or target in new_ids, (bone_id, field, target)

for bone in armature.data.bones:
    bone.select = bone.name in grid_names
assert bpy.ops.gbfr.clp_create_from_selection(
    replace_existing=True,
    preset_key="SKIRT",
    topology="GRID",
    closed=False,
    apply_header=True,
) == {"FINISHED"}
group = state.clp_groups[state.active_clp_index]
assert len(group.nodes) == 6
by_bone = {node.bone: node for node in group.nodes}
a1, a2, b1, b2, c1, c2 = (export_ids[name] for name in grid_names)
assert by_bone[a1].down == a2 and by_bone[a2].up == a1
assert by_bone[b1].side == a1 and by_bone[b1].poly == a1
assert by_bone[b2].side == a2 and by_bone[b2].poly == a2
assert by_bone[c1].side == b1 and by_bone[c2].side == b2

assert bpy.ops.gbfr.clp_rebuild_connections(topology="GRID", closed=True) == {"FINISHED"}
assert state.clp_tool_topology == "GRID" and state.clp_tool_closed is True
by_bone = {node.bone: node for node in group.nodes}
assert by_bone[a1].side == c1 and by_bone[a2].side == c2

for bone in armature.data.bones:
    bone.select = bone.name == grid_names[1]
assert bpy.ops.gbfr.clp_delete_selection() == {"FINISHED"}
by_bone = {node.bone: node for node in group.nodes}
assert a2 not in by_bone
assert by_bone[a1].down == 4095
assert by_bone[b2].side == 4095 and by_bone[b2].poly == 4095

for bone in armature.data.bones:
    bone.select = bone.name in fork_names
try:
    bpy.ops.gbfr.clp_create_from_selection(
        replace_existing=True,
        preset_key="LONG_HAIR",
        topology="GRID",
        closed=False,
    )
except RuntimeError as error:
    assert "分叉" in str(error)
else:
    raise AssertionError("grid topology unexpectedly accepted a fork")
assert bpy.ops.gbfr.clp_create_from_selection(
    replace_existing=True,
    preset_key="LONG_HAIR",
    topology="CHAINS",
    closed=False,
) == {"FINISHED"}
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
