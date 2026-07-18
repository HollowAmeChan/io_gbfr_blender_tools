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
    "VIEW3D_PT_GBFR_Cloth_Editor", "VIEW3D_PT_GBFR_Sop_Inspector",
    "VIEW3D_PT_GBFR_Animation_Preview",
):
    panel = bpy.types.Panel.bl_rna_get_subclass_py(panel_id)
    assert panel is not None and panel.bl_parent_id == "VIEW3D_PT_GBFR_Workspace", panel_id
assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Tools_Panel_Fixes") is None
assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Tools_Panel_Utilities") is None
assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Tools_Panel_Materials") is None
assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Tools_Panel_Advanced") is None
assert bpy.types.Panel.bl_rna_get_subclass_py("VIEW3D_PT_GBFR_Tools_Panel_Credits") is None
armature = bpy.data.armatures.new("GBFRSmokeArmature")
obj = bpy.data.objects.new("GBFRSmokeArmature", armature)
bpy.context.scene.collection.objects.link(obj)
assert obj.gbfr_cloth.enabled is False
assert obj.gbfr_sop.enabled is False
assert obj.gbfr_animation.enabled is False
bpy.ops.preferences.addon_disable(module=module)
print("GBFR cloth Blender registration smoke test passed")
