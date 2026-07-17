"""Run with: blender --background --python test/blender_smoke.py"""

import bpy


module = "io_gbfr_blender_tools"
bpy.ops.preferences.addon_enable(module=module)
assert hasattr(bpy.types.Object, "gbfr_cloth")
assert hasattr(bpy.types.Object, "gbfr_sop")
armature = bpy.data.armatures.new("GBFRSmokeArmature")
obj = bpy.data.objects.new("GBFRSmokeArmature", armature)
bpy.context.scene.collection.objects.link(obj)
assert obj.gbfr_cloth.enabled is False
assert obj.gbfr_sop.enabled is False
bpy.ops.preferences.addon_disable(module=module)
print("GBFR cloth Blender registration smoke test passed")
