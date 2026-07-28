"""Run with: blender --background --python this_file.py -- path/to/model.minfo"""

from pathlib import Path
import sys

import bpy

from io_gbfr_blender_tools.gbfr_material import (
    load_material_definitions, resolve_albedo_texture,
)
from io_gbfr_blender_tools.gbfr_material_blender import _build_nodes, _load_image
from io_gbfr_blender_tools.gbfr_workspace import resolve_model_bundle


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
assert meshes
assert sum(mesh["gbfr_material_applied"] for mesh in meshes) > 0
for mesh in meshes:
    assert mesh["gbfr_material_applied"] + mesh["gbfr_material_missing"] == len(mesh.data.materials)

materials = [material for mesh in meshes for material in mesh.data.materials]
for material in materials:
    if "gbfr_albedo_dds" not in material and not material.get("gbfr_eye_material"):
        assert material.get("gbfr_material_error") == "No resolved base-color DDS"
        continue
    node_types = {node.bl_idname for node in material.node_tree.nodes}
    assert {"ShaderNodeEmission", "ShaderNodeOutputMaterial"} <= node_types
    assert "ShaderNodeBsdfTransparent" not in node_types
    assert "ShaderNodeMixShader" not in node_types
    emission = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeEmission")
    output = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeOutputMaterial")
    assert any(
        link.from_socket == emission.outputs["Emission"]
        and link.to_socket == output.inputs["Surface"]
        for link in material.node_tree.links
    )
    if material.get("gbfr_eye_material"):
        assert sum(node.bl_idname == "ShaderNodeTexImage" for node in material.node_tree.nodes) == 3
        assert sum(node.bl_idname == "ShaderNodeMixRGB" for node in material.node_tree.nodes) == 3
    else:
        assert sum(node.bl_idname == "ShaderNodeTexImage" for node in material.node_tree.nodes) == 1
        texture = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage")
        assert any(link.from_socket == texture.outputs["Color"] and link.to_socket == emission.inputs["Color"] for link in material.node_tree.links)
        assert not any(link.from_socket == texture.outputs["Alpha"] for link in material.node_tree.links)

bundle = resolve_model_bundle(minfo)
definitions = load_material_definitions(bundle.material_json)
eye_definitions = [definition for definition in definitions if definition.is_eye_material]
if eye_definitions:
    definition = eye_definitions[0]
    eye_paths = tuple(
        resolve_albedo_texture(bundle.texture_roots, name)
        for name in (
            definition.eye_conjunctiva_name,
            definition.eye_iris_name,
            definition.eye_highlight_name,
        )
    )
    assert all(eye_paths), eye_paths
    cache = {}
    eye_images = tuple(_load_image(path, cache) for path in eye_paths)
    probe = bpy.data.materials.new("GBFR Eye Material Probe")
    _build_nodes(probe, None, eye_images)
    probe_types = {node.bl_idname for node in probe.node_tree.nodes}
    assert {"ShaderNodeTexImage", "ShaderNodeMixRGB", "ShaderNodeEmission"} <= probe_types
    assert "ShaderNodeMixShader" not in probe_types
    probe_emission = next(node for node in probe.node_tree.nodes if node.bl_idname == "ShaderNodeEmission")
    assert any(link.to_socket == probe_emission.inputs["Color"] for link in probe.node_tree.links)

print(
    f"GBFR material import smoke passed: {len(meshes)} meshes / "
    f"{sum(mesh['gbfr_material_applied'] for mesh in meshes)} applied / "
    f"{sum(mesh['gbfr_material_missing'] for mesh in meshes)} unsupported or missing / "
    f"{len(eye_definitions)} eye definitions verified"
)
