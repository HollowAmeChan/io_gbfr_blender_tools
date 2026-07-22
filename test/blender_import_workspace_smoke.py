"""Import a real Modtools workspace model with Blender in background mode."""

import os
from pathlib import Path

import bpy


module = "io_gbfr_blender_tools"
minfo_path = Path(os.environ["GBFR_TEST_MINFO"]).resolve()
bpy.ops.preferences.addon_enable(module=module)

result = bpy.ops.gbfr.import_mesh(filepath=str(minfo_path), import_scale=1.0, bone_scale=1.0)
assert result == {"FINISHED"}, result

session = bpy.context.scene.gbfr_workspace.active_session
assert session is not None and session.gbfr_session.enabled
objects = tuple(session.objects)
lod_objects = tuple(obj for obj in objects if obj.type == "EMPTY" and obj.name.startswith(("lod", "shadowlod")))
meshes = tuple(obj for obj in objects if obj.type == "MESH")
lod_names = {obj.name.split(".", 1)[0] for obj in lod_objects}
assert lod_names == {"lod0", "lod1", "lod2", "lod3"}, lod_names
assert len(meshes) >= len(lod_objects), (len(meshes), len(lod_objects))
assert all(mesh.get("gbfr_lod") in lod_names for mesh in meshes)
assert all(mesh.data.uv_layers.get("UV0") is not None for mesh in meshes)

max_influences = 0
for mesh in meshes:
    for vertex in mesh.data.vertices:
        max_influences = max(max_influences, len(vertex.groups))
assert max_influences <= 8, max_influences

uv1_meshes = sum(mesh.data.uv_layers.get("UV1") is not None for mesh in meshes)
color_meshes = sum(bool(mesh.data.color_attributes) for mesh in meshes)
print(
    "GBFR v2 workspace import smoke passed:",
    f"lods={sorted(lod_names)} meshes={len(meshes)} uv1={uv1_meshes} colors={color_meshes} max_weights={max_influences}",
)
bpy.ops.preferences.addon_disable(module=module)
