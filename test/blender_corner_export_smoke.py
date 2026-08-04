"""Run with: blender --background --factory-startup --python this_file.py"""

import struct

import bpy


bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")

from io_gbfr_blender_tools.gbfr_model_export_v2 import build_mesh_export_data


mesh = bpy.data.meshes.new("GBFR sharp corner test")
mesh.from_pydata(
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
    [],
    [(0, 1, 2), (1, 0, 3)],
)
for polygon in mesh.polygons:
    polygon.use_smooth = True
uv = mesh.uv_layers.new(name="UV0")
uv_by_vertex = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, 1.0))
for loop in mesh.loops:
    uv.data[loop.index].uv = uv_by_vertex[loop.vertex_index]

expected_normals = [(0.0, 0.0, 1.0)] * 3 + [(0.0, 1.0, 0.0)] * 3
mesh.normals_split_custom_set(expected_normals)
mesh.calc_tangents()

records, loop_to_export_index = build_mesh_export_data(mesh)
assert len(records) == 6, len(records)
for loop_index, expected in enumerate(expected_normals):
    record = records[loop_to_export_index[loop_index]]
    exported = tuple(-value for value in struct.unpack("<eee", record["vertex_buffer"][1]))
    assert all(abs(left - right) < 1e-3 for left, right in zip(exported, expected)), (
        loop_index, exported, expected,
    )

assert loop_to_export_index[0] != loop_to_export_index[4]
assert loop_to_export_index[1] != loop_to_export_index[3]
print("GBFR corner export smoke passed: sharp normals produced 6 game vertices from 4 Blender vertices")
