"""Run with: blender --background --python this_file.py -- pl.minfo fp.minfo"""

from pathlib import Path
import sys

import bpy


try:
    separator = sys.argv.index("--")
    pl_minfo = Path(sys.argv[separator + 1]).resolve()
    fp_minfo = Path(sys.argv[separator + 2]).resolve()
except (ValueError, IndexError):
    raise SystemExit("Pass body and face workspace minfo paths after --")

bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
assert bpy.ops.gbfr.import_mesh(filepath=str(pl_minfo), import_scale=1.0) == {"FINISHED"}
assert bpy.ops.gbfr.import_mesh(filepath=str(fp_minfo), import_scale=1.0) == {"FINISHED"}

from io_gbfr_blender_tools.gbfr_session import (
    active_session_armature, active_session_collection, object_session_collection,
    session_collections,
)

sessions = session_collections(bpy.context.scene)
assert len(sessions) == 2, [collection.name for collection in sessions]
by_model = {collection.gbfr_session.model_id: collection for collection in sessions}
pl_session = by_model["pl1400"]
fp_session = by_model["fp1400"]
assert pl_session.gbfr_session.armature != fp_session.gbfr_session.armature
assert pl_session.gbfr_session.mesh != fp_session.gbfr_session.mesh
assert bpy.context.scene.gbfr_workspace.active_session == fp_session

# Session lookup is used by Blender poll callbacks and must never mutate Scene data.
for selected in bpy.context.selected_objects:
    selected.select_set(False)
pl_session.gbfr_session.armature.select_set(True)
bpy.context.view_layer.objects.active = pl_session.gbfr_session.armature
assert active_session_collection(bpy.context) == pl_session
assert bpy.context.scene.gbfr_workspace.active_session == fp_session

custom_collection = bpy.data.collections.new("User Replacement Assets")
bpy.context.scene.collection.children.link(custom_collection)
custom_mesh = bpy.data.meshes.new("UserMesh")
custom_object = bpy.data.objects.new("User Replacement", custom_mesh)
custom_collection.objects.link(custom_object)
custom_object.parent = fp_session.gbfr_session.armature
assert object_session_collection(custom_object, bpy.context.scene) is None
for selected in bpy.context.selected_objects:
    selected.select_set(False)
custom_object.select_set(True)
bpy.context.view_layer.objects.active = custom_object
assert active_session_collection(bpy.context) == fp_session
assert active_session_armature(bpy.context) == fp_session.gbfr_session.armature

assert bpy.ops.gbfr.activate_session(collection_name=pl_session.name) == {"FINISHED"}
assert active_session_collection(bpy.context) == pl_session
assert bpy.context.view_layer.objects.active == pl_session.gbfr_session.armature
assert custom_object.name in custom_collection.objects

for selected in bpy.context.selected_objects:
    selected.select_set(False)
custom_object.select_set(True)
bpy.context.view_layer.objects.active = custom_object
assert active_session_collection(bpy.context) == pl_session
assert active_session_armature(bpy.context) == pl_session.gbfr_session.armature
assert bpy.ops.gbfr.activate_session(collection_name=pl_session.name) == {"FINISHED"}

pl_node = pl_session.gbfr_session.armature.gbfr_cloth.clp_groups[0].nodes[0]
original_friction = pl_node.friction
fp_material_missing = fp_session.gbfr_session.mesh.get("gbfr_material_missing")
pl_node.friction = original_friction + 0.123
assert bpy.ops.gbfr.restore_session_data() == {"FINISHED"}
assert abs(pl_session.gbfr_session.armature.gbfr_cloth.clp_groups[0].nodes[0].friction - original_friction) < 1e-6
assert not fp_session.gbfr_session.armature.gbfr_cloth.enabled
assert fp_session.gbfr_session.mesh.get("gbfr_material_missing") == fp_material_missing
assert custom_object.name in custom_collection.objects

print(
    "GBFR multi-session smoke passed: "
    f"{pl_session.name} / {fp_session.name} / custom collection isolated"
)
