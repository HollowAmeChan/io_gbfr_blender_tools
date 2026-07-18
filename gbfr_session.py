"""Collection-scoped GBFR import sessions."""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import BoolProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup


class GBFRSessionProperties(PropertyGroup):
    enabled: BoolProperty(default=False)
    source_minfo_path: StringProperty(name="minfo", subtype="FILE_PATH")
    resolved_minfo_path: StringProperty(name="解析文件", subtype="FILE_PATH")
    workspace_path: StringProperty(name="工作区", subtype="FILE_PATH")
    character_id: StringProperty(name="角色")
    model_id: StringProperty(name="模型")
    armature: PointerProperty(name="骨架", type=bpy.types.Object)
    mesh: PointerProperty(name="模型", type=bpy.types.Object)
    last_status: StringProperty(name="状态")


class GBFRSceneWorkspaceProperties(PropertyGroup):
    active_session: PointerProperty(name="当前工作区", type=bpy.types.Collection)


def configure_session(collection, bundle, source_minfo_path, armature, mesh, scene=None) -> None:
    state = collection.gbfr_session
    state.enabled = True
    state.source_minfo_path = str(Path(source_minfo_path).resolve())
    state.resolved_minfo_path = str(bundle.minfo)
    state.workspace_path = str(bundle.workspace_json)
    state.character_id = bundle.character_id
    state.model_id = bundle.model_id
    state.armature = armature
    state.mesh = mesh
    state.last_status = "已导入"
    (scene or bpy.context.scene).gbfr_workspace.active_session = collection
    armature["gbfr_session_collection"] = collection.name
    mesh["gbfr_session_collection"] = collection.name


def session_collections(scene) -> list[bpy.types.Collection]:
    return sorted(
        (
            collection for collection in scene.collection.children_recursive
            if hasattr(collection, "gbfr_session") and collection.gbfr_session.enabled
        ),
        key=lambda collection: (collection.gbfr_session.model_id.casefold(), collection.name.casefold()),
    )


def object_session_collection(obj, scene=None):
    if obj is None:
        return None
    available = set(session_collections(scene or bpy.context.scene))
    for collection in obj.users_collection:
        if collection in available:
            return collection
    return None


def active_session_collection(context):
    selected = object_session_collection(context.object, context.scene)
    if selected is not None:
        if context.scene.gbfr_workspace.active_session != selected:
            context.scene.gbfr_workspace.active_session = selected
        return selected
    collection = context.scene.gbfr_workspace.active_session
    if collection is not None and collection in session_collections(context.scene):
        return collection
    sessions = session_collections(context.scene)
    return sessions[0] if len(sessions) == 1 else None


def active_session_armature(context):
    collection = active_session_collection(context)
    if collection is None:
        return None
    armature = collection.gbfr_session.armature
    if armature is not None and armature.name in collection.objects and armature.type == "ARMATURE":
        return armature
    return next((obj for obj in collection.objects if obj.type == "ARMATURE"), None)


def active_session_mesh(context):
    collection = active_session_collection(context)
    if collection is None:
        return None
    mesh = collection.gbfr_session.mesh
    if mesh is not None and mesh.name in collection.objects and mesh.type == "MESH":
        return mesh
    return next((obj for obj in collection.objects if obj.type == "MESH"), None)


def activate_session(context, collection, select_armature=True) -> None:
    if collection is None or not collection.gbfr_session.enabled:
        raise ValueError("所选集合不是 GBFR minfo 工作区")
    context.scene.gbfr_workspace.active_session = collection
    if not select_armature:
        return
    armature = collection.gbfr_session.armature
    if armature is None:
        armature = next((obj for obj in collection.objects if obj.type == "ARMATURE"), None)
    if armature is None:
        return
    for obj in context.selected_objects:
        obj.select_set(False)
    armature.hide_set(False)
    armature.select_set(True)
    context.view_layer.objects.active = armature


classes = (GBFRSessionProperties, GBFRSceneWorkspaceProperties)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Collection.gbfr_session = PointerProperty(type=GBFRSessionProperties)
    bpy.types.Scene.gbfr_workspace = PointerProperty(type=GBFRSceneWorkspaceProperties)


def unregister():
    if hasattr(bpy.types.Scene, "gbfr_workspace"):
        del bpy.types.Scene.gbfr_workspace
    if hasattr(bpy.types.Collection, "gbfr_session"):
        del bpy.types.Collection.gbfr_session
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
