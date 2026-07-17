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
meshes = [
    obj for obj in bpy.context.scene.objects
    if obj.type == "MESH" and "gbfr_material_json" in obj
]
assert len(meshes) == 1, len(meshes)
mesh = meshes[0]
assert mesh["gbfr_material_applied"] == len(mesh.data.materials)
assert mesh["gbfr_material_missing"] == 0

eye_materials = []
for material in mesh.data.materials:
    node_types = {node.bl_idname for node in material.node_tree.nodes}
    assert {"ShaderNodeEmission", "ShaderNodeBsdfTransparent", "ShaderNodeMixShader"} <= node_types
    assert material.surface_render_method == "BLENDED"
    if material.get("gbfr_eye_material"):
        eye_materials.append(material)
        assert sum(node.bl_idname == "ShaderNodeTexImage" for node in material.node_tree.nodes) == 3
        assert sum(node.bl_idname == "ShaderNodeMixRGB" for node in material.node_tree.nodes) == 3
    else:
        assert sum(node.bl_idname == "ShaderNodeTexImage" for node in material.node_tree.nodes) == 1

print(
    f"GBFR material import smoke passed: {len(mesh.data.materials)} materials / "
    f"{len(eye_materials)} composite eyes / 0 missing"
)
