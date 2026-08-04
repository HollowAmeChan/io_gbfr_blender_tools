"""Central minfo-session workspace UI."""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Menu, Operator, Panel

from .gbfr_session import (
    activate_session, active_session_armature, active_session_collection,
    active_session_mesh, active_session_meshes, active_session_root,
    resolve_session_bundle, session_collections,
)


class GBFR_MT_Sessions(Menu):
    bl_label = "minfo 工作区"
    bl_idname = "GBFR_MT_minfo_sessions"

    def draw(self, context):
        layout = self.layout
        for collection in session_collections(context.scene):
            operator = layout.operator(
                "gbfr.activate_session",
                text=collection.name,
                icon="OUTLINER_COLLECTION",
            )
            operator.collection_name = collection.name


class GBFR_OT_ActivateSession(Operator):
    bl_idname = "gbfr.activate_session"
    bl_label = "切换 minfo 工作区"
    bl_options = {"UNDO"}

    collection_name: StringProperty()

    def execute(self, context):
        collection = bpy.data.collections.get(self.collection_name)
        try:
            activate_session(context, collection)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class GBFR_OT_SelectSessionObject(Operator):
    bl_idname = "gbfr.select_session_object"
    bl_label = "选择工作区对象"
    bl_options = {"UNDO"}

    target: EnumProperty(items=(
        ("ROOT", "根对象", ""),
        ("ARMATURE", "骨架", ""),
        ("MESH", "主模型", ""),
    ))

    def execute(self, context):
        if self.target == "ROOT":
            obj = active_session_root(context)
        elif self.target == "ARMATURE":
            obj = active_session_armature(context)
        else:
            obj = active_session_mesh(context)
        if obj is None:
            return {"CANCELLED"}
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.hide_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class GBFR_OT_RestoreSessionData(Operator):
    bl_idname = "gbfr.restore_session_data"
    bl_label = "恢复工作区数据"
    bl_description = "丢弃当前会话的材质、Cloth、SOP 与动画列表编辑并重新读取工作区；不重建模型和骨架"
    bl_options = {"UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, title="恢复工作区数据")

    def execute(self, context):
        collection = active_session_collection(context)
        armature = active_session_armature(context)
        meshes = active_session_meshes(context)
        if collection is None or not meshes:
            return {"CANCELLED"}
        state = collection.gbfr_session
        try:
            bundle = resolve_session_bundle(collection)
            from .gbfr_material_blender import apply_workspace_materials
            from .gbfr_cloth_blender import populate_cloth_state
            from .gbfr_sop_blender import populate_sop_state
            from .gbfr_animation_blender import populate_animation_state

            for mesh in meshes:
                apply_workspace_materials(mesh, bundle)
            if armature is not None:
                populate_cloth_state(armature, bundle)
                populate_sop_state(armature, bundle)
                populate_animation_state(armature, bundle)
            state.resolved_minfo_path = str(bundle.minfo)
            state.workspace_path = str(bundle.workspace_json)
            state.last_status = "已恢复工作区数据"
        except Exception as error:
            state.last_status = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, state.last_status)
        return {"FINISHED"}


class GBFR_OT_ExportSessionModel(Operator):
    bl_idname = "gbfr.export_session_model"
    bl_label = "导出模型"
    bl_description = "选择 workspace.json，将当前模型直接导出到该工作区的 unpack"

    def execute(self, context):
        collection = active_session_collection(context)
        if collection is None:
            return {"CANCELLED"}
        activate_session(context, collection)
        return bpy.ops.gbfr.export_mesh("INVOKE_DEFAULT")


class GBFR_PT_Workspace(Panel):
    bl_label = "GBFR 工作区"
    bl_idname = "VIEW3D_PT_GBFR_Workspace"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GBFR"

    def draw(self, context):
        layout = self.layout
        sessions = session_collections(context.scene)
        collection = active_session_collection(context)

        row = layout.row(align=True)
        if sessions:
            label = collection.name if collection else "选择工作区"
            row.menu(GBFR_MT_Sessions.bl_idname, text=label, icon="OUTLINER_COLLECTION")
        row.operator("gbfr.import_mesh", text="", icon="IMPORT")

        if collection is None:
            return
        state = collection.gbfr_session
        source = layout.row(align=True)
        path = source.row(align=True)
        path.enabled = False
        path.prop(state, "source_minfo_path", text="", icon="FILE_3D")
        open_folder = source.operator("wm.path_open", text="", icon="FILE_FOLDER")
        open_folder.filepath = str(Path(state.source_minfo_path).parent)

        controls = layout.row(align=True)
        controls.operator("gbfr.restore_session_data", text="恢复", icon="FILE_REFRESH")
        controls.operator("gbfr.export_session_model", text="导出到工作区", icon="EXPORT")

        if state.last_status and state.last_status not in {"已导入", "已恢复工作区数据"}:
            layout.label(text=state.last_status, icon="INFO")


class GBFR_PT_SessionObjects(Panel):
    bl_label = "对象"
    bl_idname = "VIEW3D_PT_GBFR_Session_Objects"
    bl_parent_id = GBFR_PT_Workspace.bl_idname
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GBFR"

    @classmethod
    def poll(cls, context):
        return active_session_collection(context) is not None

    def draw(self, context):
        layout = self.layout
        collection = active_session_collection(context)
        root = active_session_root(context)
        armature = active_session_armature(context)
        meshes = active_session_meshes(context)

        row = layout.row(align=True)
        root_button = row.operator("gbfr.select_session_object", text=root.name if root else "根对象", icon="OBJECT_ORIGIN")
        root_button.target = "ROOT"
        armature_button = row.operator("gbfr.select_session_object", text=armature.name if armature else "骨架", icon="ARMATURE_DATA")
        armature_button.target = "ARMATURE"
        mesh_button = row.operator("gbfr.select_session_object", text=f"模型 {len(meshes)}", icon="MESH_DATA")
        mesh_button.target = "MESH"
        row.prop(collection, "hide_viewport", text="", icon="HIDE_OFF" if not collection.hide_viewport else "HIDE_ON")

        if armature is not None and "Magic" in armature:
            magic = layout.row(align=True)
            magic.label(text="minfo Magic")
            magic.prop(armature, '["Magic"]', text="")


class GBFR_PT_SessionMaterials(Panel):
    bl_label = "材质"
    bl_idname = "VIEW3D_PT_GBFR_Session_Materials"
    bl_parent_id = GBFR_PT_Workspace.bl_idname
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GBFR"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return active_session_mesh(context) is not None

    def draw(self, context):
        meshes = active_session_meshes(context)
        layout = self.layout
        summary = layout.row(align=True)
        material_count = sum(len(mesh.data.materials) for mesh in meshes)
        summary.label(text=f"{len(meshes)} 个 Mesh / {material_count} 个材质槽", icon="MATERIAL")
        missing = sum(int(mesh.get("gbfr_material_missing", 0)) for mesh in meshes)
        if missing:
            summary.alert = True
            summary.label(text=f"缺少 {missing}", icon="ERROR")
        for mesh in meshes:
            row = layout.row(align=True)
            row.label(text=f"{mesh.get('gbfr_lod', '?')} / {mesh.name}", icon="MESH_DATA")
            row.label(text=str(len(mesh.data.materials)))


classes = (
    GBFR_MT_Sessions, GBFR_OT_ActivateSession, GBFR_OT_SelectSessionObject,
    GBFR_OT_RestoreSessionData, GBFR_OT_ExportSessionModel,
    GBFR_PT_Workspace, GBFR_PT_SessionObjects, GBFR_PT_SessionMaterials,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
