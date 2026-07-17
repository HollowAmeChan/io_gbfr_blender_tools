"""Build simple unlit Blender materials from workspace DDS textures."""

from __future__ import annotations

from pathlib import Path

import bpy

from .gbfr_material import MaterialError, load_material_definitions, resolve_albedo_texture


def _configure_alpha_blend(material: bpy.types.Material) -> None:
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "BLENDED"
    elif hasattr(material, "blend_method"):
        material.blend_method = "BLEND"
    if hasattr(material, "use_transparency_overlap"):
        material.use_transparency_overlap = False
    if hasattr(material, "show_transparent_back"):
        material.show_transparent_back = False


def _build_nodes(
    material: bpy.types.Material,
    image: bpy.types.Image | None,
    eye_images: tuple[bpy.types.Image, bpy.types.Image, bpy.types.Image] | None = None,
) -> None:
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (520, 40)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (300, 40)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (40, -100)
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (40, 100)
    emission.inputs["Strength"].default_value = 1.0

    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])

    if eye_images is not None:
        previous_color = None
        roles = ("Conjunctiva", "Iris", "Highlight")
        for index, (role, eye_image) in enumerate(zip(roles, eye_images)):
            texture = nodes.new("ShaderNodeTexImage")
            texture.name = f"GBFR {role}"
            texture.label = role
            texture.location = (-520, 240 - index * 220)
            texture.image = eye_image
            texture.interpolation = "Linear"
            texture.extension = "REPEAT"
            blend = nodes.new("ShaderNodeMixRGB")
            blend.name = f"GBFR Mix {role}"
            blend.label = f"Mix {role} by alpha"
            blend.location = (-220 + index * 190, 160 - index * 60)
            links.new(texture.outputs["Alpha"], blend.inputs[0])
            links.new(texture.outputs["Color"], blend.inputs[2])
            if previous_color is None:
                blend.inputs[1].default_value = (0.94, 0.92, 0.90, 1.0)
            else:
                links.new(previous_color, blend.inputs[1])
            previous_color = blend.outputs["Color"]
        links.new(previous_color, emission.inputs["Color"])
        mix.inputs[0].default_value = 1.0
    elif image is None:
        emission.inputs["Color"].default_value = (0.8, 0.2, 0.8, 1.0)
        mix.inputs[0].default_value = 1.0
        return
    else:
        texture = nodes.new("ShaderNodeTexImage")
        texture.location = (-260, 100)
        texture.image = image
        texture.interpolation = "Linear"
        texture.extension = "REPEAT"
        links.new(texture.outputs["Color"], emission.inputs["Color"])
        links.new(texture.outputs["Alpha"], mix.inputs[0])


def _load_image(path: Path, cache: dict[Path, bpy.types.Image]) -> bpy.types.Image:
    image = cache.get(path)
    if image is None:
        image = bpy.data.images.load(str(path), check_existing=True)
        image.colorspace_settings.name = "sRGB"
        image.alpha_mode = "STRAIGHT"
        cache[path] = image
    return image


def apply_workspace_materials(mesh_object: bpy.types.Object, bundle) -> tuple[int, int]:
    """Apply vars/0.mmat.json materials. Returns (applied, missing)."""
    material_json = bundle.material_json
    if material_json is None:
        mesh_object["gbfr_material_error"] = "vars/0.mmat.json was not found"
        return 0, len(mesh_object.data.materials)

    try:
        definitions = load_material_definitions(material_json)
    except MaterialError as error:
        mesh_object["gbfr_material_error"] = str(error)
        return 0, len(mesh_object.data.materials)

    applied = 0
    missing = 0
    image_cache: dict[Path, bpy.types.Image] = {}
    for material in mesh_object.data.materials:
        material_id = int(material.get("MaterialID", -1))
        definition = definitions[material_id] if 0 <= material_id < len(definitions) else None
        texture_path = (
            resolve_albedo_texture(bundle.workspace_root, definition.albedo_name)
            if definition is not None and definition.albedo_name else None
        )
        image = None
        eye_paths = None
        eye_images = None
        if definition is not None and definition.is_eye_material:
            eye_paths = tuple(
                resolve_albedo_texture(bundle.workspace_root, name)
                for name in (
                    definition.eye_conjunctiva_name,
                    definition.eye_iris_name,
                    definition.eye_highlight_name,
                )
            )
        if texture_path is not None:
            try:
                image = _load_image(texture_path, image_cache)
            except RuntimeError as error:
                material["gbfr_material_error"] = str(error)
        elif eye_paths is not None and all(eye_paths):
            try:
                eye_images = tuple(_load_image(path, image_cache) for path in eye_paths)
            except RuntimeError as error:
                material["gbfr_material_error"] = str(error)
                eye_images = None

        _configure_alpha_blend(material)
        _build_nodes(material, image, eye_images)
        material["gbfr_mmat_json"] = str(material_json)
        material["gbfr_material_id"] = material_id
        if definition is not None:
            material["gbfr_alpha_enabled"] = definition.alpha_enabled
            if definition.albedo_name:
                material["gbfr_albedo_name"] = definition.albedo_name
            if definition.is_eye_material:
                material["gbfr_eye_material"] = True
        if texture_path is not None and image is not None:
            material["gbfr_albedo_dds"] = str(texture_path)
            applied += 1
        elif eye_paths is not None and eye_images is not None:
            for role, path in zip(("conjunctiva", "iris", "highlight"), eye_paths):
                material[f"gbfr_eye_{role}_dds"] = str(path)
            applied += 1
        else:
            missing += 1
            material["gbfr_material_error"] = material.get(
                "gbfr_material_error", "No base albedo DDS was resolved"
            )

    mesh_object["gbfr_material_json"] = str(material_json)
    mesh_object["gbfr_material_applied"] = applied
    mesh_object["gbfr_material_missing"] = missing
    print(f"GBFR materials: {applied} applied, {missing} missing from {material_json}")
    return applied, missing
