"""Workspace-aware entry point for the v2 model importer."""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import FloatProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from . import gbfr_model_v2
from .gbfr_workspace import resolve_model_bundle


def read_some_data(context, filepath, import_scale=1.0, bone_scale=1.0):
    source_minfo_path = str(Path(filepath).expanduser().resolve())
    bundle = resolve_model_bundle(filepath)
    collection = bpy.data.collections.new(f"GBFR | {bundle.model_id}")
    context.scene.collection.children.link(collection)

    try:
        imported = gbfr_model_v2.read_some_data(
            context,
            str(bundle.minfo),
            [str(path) for path in bundle.mmeshes],
            import_scale=import_scale,
            bone_scale=bone_scale,
            model_collection=collection,
            skeleton_filepath=str(bundle.skeleton) if bundle.skeleton else None,
            return_objects=True,
        )
        root = imported["root"]
        armature = imported["armature"]
        meshes = imported["meshes"]

        from .gbfr_material_blender import apply_workspace_materials
        for mesh in meshes:
            apply_workspace_materials(mesh, bundle)

        if armature is not None:
            from .gbfr_cloth_blender import populate_cloth_state
            from .gbfr_sop_blender import populate_sop_state
            from .gbfr_animation_blender import populate_animation_state

            populate_cloth_state(armature, bundle)
            populate_sop_state(armature, bundle)
            populate_animation_state(armature, bundle)

        from .gbfr_session import configure_session
        configure_session(
            collection,
            bundle,
            source_minfo_path,
            root,
            armature,
            meshes,
            context.scene,
        )
    except Exception:
        bpy.data.collections.remove(collection)
        raise

    return {"FINISHED"}


class ImportSomeData(Operator, ImportHelper):
    """Import a GBFR model from a Modtools workspace."""

    bl_idname = "gbfr.import_mesh"
    bl_label = "导入 minfo"
    bl_description = "从 GBFR Modtools 工作区导入 minfo 及其全部 LOD"

    filename_ext = ".minfo"
    filter_glob: StringProperty(default="*.minfo", options={"HIDDEN"}, maxlen=255)
    import_scale: FloatProperty(name="模型缩放", default=1.0)
    bone_scale: FloatProperty(name="骨骼显示长度", default=1.0, min=0.01)

    def execute(self, context):
        try:
            return read_some_data(context, self.filepath, self.import_scale, self.bone_scale)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


def menu_func_import(self, _context):
    self.layout.operator(ImportSomeData.bl_idname, text="Granblue Fantasy Relink (.minfo)")


def register():
    bpy.utils.register_class(ImportSomeData)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(ImportSomeData)
