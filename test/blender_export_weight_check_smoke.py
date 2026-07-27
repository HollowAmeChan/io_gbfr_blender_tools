"""Run with: blender --background --factory-startup --python this_file.py"""

import bpy


bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")

from io_gbfr_blender_tools.gbfr_export import _run_export_weight_check, inspect_export_weights


root = bpy.data.objects.new("ExportRoot", None)
lod = bpy.data.objects.new("lod0", None)
mesh_data = bpy.data.meshes.new("WeightProbe")
mesh_data.from_pydata(
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)],
    [],
    [],
)
mesh = bpy.data.objects.new("WeightProbe", mesh_data)
bpy.context.scene.collection.objects.link(root)
bpy.context.scene.collection.objects.link(lod)
bpy.context.scene.collection.objects.link(mesh)
lod.parent = root
mesh.parent = lod

groups = [mesh.vertex_groups.new(name=f"Bone{index}") for index in range(5)]
groups[0].add([0], 0.5, "REPLACE")
groups[1].add([0], 0.5, "REPLACE")
groups[0].add([1], 0.5, "REPLACE")
groups[1].add([1], 0.25, "REPLACE")
for group in groups:
    group.add([2], 0.2, "REPLACE")

result = inspect_export_weights(root)
assert result["mesh_count"] == 1
assert result["vertex_count"] == 4
assert result["unnormalized"] == 2
assert result["over_limit"] == 1
assert result["details"] == (("WeightProbe", 2, 1),)

groups[1].add([1], 0.25, "ADD")
groups[0].add([3], 1.0, "REPLACE")
result = inspect_export_weights(root)
assert result["unnormalized"] == 0
assert result["over_limit"] == 1

session = bpy.data.collections.new("WeightCheckSession")
bpy.context.scene.collection.children.link(session)
session.objects.link(root)
session.gbfr_session.enabled = True
session.gbfr_session.model_id = "pl9999"
session.gbfr_session.root = root
bpy.context.scene.gbfr_workspace.active_session = session
result = _run_export_weight_check(bpy.context)
assert result is not None
assert session.gbfr_session.weight_check_completed
assert session.gbfr_session.weight_check_unnormalized == 0
assert session.gbfr_session.weight_check_over_four == 1
assert "WeightProbe" in session.gbfr_session.weight_check_details

print("GBFR export weight check smoke passed")
