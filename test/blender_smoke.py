"""Run with: blender --background --python test/blender_smoke.py"""

import bpy


module = "io_gbfr_blender_tools"
bpy.ops.preferences.addon_enable(module=module)
assert hasattr(bpy.types.Object, "gbfr_cloth")
assert hasattr(bpy.types.Object, "gbfr_sop")
assert hasattr(bpy.types.Object, "gbfr_animation")
assert hasattr(bpy.types.Collection, "gbfr_session")
assert hasattr(bpy.types.Scene, "gbfr_workspace")
assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Workspace") is not None
for panel_id in (
    "VIEW3D_PT_GBFR_Session_Objects", "VIEW3D_PT_GBFR_Session_Materials",
    "VIEW3D_PT_GBFR_Cloth_Editor", "VIEW3D_PT_GBFR_Clp_Editor",
    "VIEW3D_PT_GBFR_Clh_Editor", "VIEW3D_PT_GBFR_Sop_Inspector",
    "VIEW3D_PT_GBFR_Animation_Preview",
):
    panel = bpy.types.Panel.bl_rna_get_subclass_py(panel_id)
    assert panel is not None and panel.bl_parent_id == "VIEW3D_PT_GBFR_Workspace", panel_id
assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Tools_Panel_Fixes") is None
assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Tools_Panel_Utilities") is None
assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Tools_Panel_Materials") is None
assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Tools_Panel_Advanced") is None
assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Tools_Panel_Credits") is None
utility_panel = bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Restored_Utilities")
assert utility_panel is not None
assert utility_panel.bl_category == "GBFR"
assert not getattr(utility_panel, "bl_parent_id", "")
armature = bpy.data.armatures.new("GBFRSmokeArmature")
obj = bpy.data.objects.new("GBFRSmokeArmature", armature)
bpy.context.scene.collection.objects.link(obj)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.mode_set(mode="EDIT")
bone = armature.edit_bones.new("_000")
bone.head = (0.0, 0.0, 0.0)
bone.tail = (0.0, 0.0, 1.0)
bpy.ops.object.mode_set(mode="OBJECT")
armature.bones["_000"]["gbfr_bone_id"] = 0
armature.bones["_000"]["gbfr_original_name"] = "_000"
assert bpy.ops.armature.translate_bones_to_unity_blender() == {"FINISHED"}
assert armature.bones.get("Hips") is not None
assert bpy.ops.armature.translate_bones_to_gbfr() == {"FINISHED"}
assert armature.bones.get("_000") is not None
from io_gbfr_blender_tools.bone_name_mappings import BONE_NAME_MAPPINGS
assert BONE_NAME_MAPPINGS["_830"][0].endswith(".L")
assert "Brow_01_L" in BONE_NAME_MAPPINGS["_830"]
mesh_data = bpy.data.meshes.new("GBFRSmokeMesh")
mesh_obj = bpy.data.objects.new("GBFRSmokeMesh", mesh_data)
bpy.context.scene.collection.objects.link(mesh_obj)
mesh_obj.parent = obj
mesh_obj.vertex_groups.new(name="_000")
mesh_obj.vertex_groups.new(name="unused")
obj.select_set(False)
mesh_obj.select_set(True)
bpy.context.view_layer.objects.active = mesh_obj
assert bpy.ops.armature.translate_bones_to_unity_blender() == {"FINISHED"}
assert armature.bones.get("Hips") is not None
assert bpy.ops.armature.translate_bones_to_gbfr() == {"FINISHED"}
assert armature.bones.get("_000") is not None
assert bpy.ops.mesh.remove_unused_vertex_groups() == {"FINISHED"}
assert mesh_obj.vertex_groups.get("_000") is not None
assert mesh_obj.vertex_groups.get("unused") is None
assert obj.gbfr_cloth.enabled is False
assert obj.gbfr_sop.enabled is False
assert obj.gbfr_animation.enabled is False
bpy.ops.preferences.addon_disable(module=module)
print("GBFR Blender registration and restored utilities smoke test passed")
