"""Export v2 model hierarchies into a GBFR Modtools workspace."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

import bpy
from bpy.props import FloatProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from . import gbfr_model_export_v2
from .gbfr_workspace import resolve_model_export_targets


def _hierarchy(root):
    result = []
    pending = [root]
    while pending:
        obj = pending.pop(0)
        result.append(obj)
        pending.extend(obj.children)
    return tuple(result)


def _duplicate_hierarchy(root, collection):
    mapping = {}
    for source in _hierarchy(root):
        duplicate = source.copy()
        if source.data is not None:
            duplicate.data = source.data.copy()
        collection.objects.link(duplicate)
        mapping[source] = duplicate

    for source, duplicate in mapping.items():
        duplicate.parent = mapping.get(source.parent)
        for modifier in duplicate.modifiers:
            if modifier.type == "ARMATURE" and modifier.object in mapping:
                modifier.object = mapping[modifier.object]
    return mapping[root]


def _atomic_install(source, target, temporary_files):
    if not source.is_file():
        raise FileNotFoundError(f"导出结果缺失: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".gbfr-export.tmp")
    shutil.copy2(source, temporary)
    temporary_files.append((temporary, target))


def _install_workspace_export(staging_root, targets):
    staging_root = Path(staging_root)
    model_directory = staging_root / "model" / targets.model_id[:2] / targets.model_id
    files = [
        (model_directory / f"{targets.model_id}.minfo", targets.minfo),
    ]
    if targets.skeleton is not None:
        files.append((model_directory / f"{targets.model_id}.skeleton", targets.skeleton))
    for target in targets.mmeshes:
        stream_level = target.parent.name
        files.append((
            staging_root / "model_streaming" / stream_level / f"{targets.model_id}.mmesh",
            target,
        ))

    temporary_files = []
    try:
        for source, target in files:
            _atomic_install(source, target, temporary_files)
        for temporary, target in temporary_files:
            os.replace(temporary, target)
    finally:
        for temporary, _target in temporary_files:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


class ExportSomeData(Operator, ImportHelper):
    """Export the active minfo session to workspace unpack."""

    bl_idname = "gbfr.export_mesh"
    bl_label = "导出到 GBFR 工作区"
    bl_description = "选择 workspace.json，将当前模型的全部 LOD 覆盖到 unpack"

    filename_ext = ".json"
    filter_glob: StringProperty(default="workspace.json;*.json", options={"HIDDEN"}, maxlen=255)
    export_scale: FloatProperty(name="导出缩放", default=1.0)

    def invoke(self, context, _event):
        from .gbfr_session import active_session_collection
        collection = active_session_collection(context)
        if collection is not None and collection.gbfr_session.workspace_path:
            self.filepath = collection.gbfr_session.workspace_path
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "export_scale")
        from .gbfr_session import active_session_collection
        collection = active_session_collection(context)
        box = layout.box()
        if collection is None:
            box.label(text="没有激活的 minfo 工作区", icon="ERROR")
            return
        state = collection.gbfr_session
        box.label(text=f"当前模型: {state.model_id}", icon="FILE_3D")
        try:
            targets = resolve_model_export_targets(self.filepath, state.model_id)
        except Exception as error:
            box.alert = True
            box.label(text=str(error), icon="ERROR")
            return
        box.label(text="将覆盖以下 unpack 文件", icon="EXPORT")
        for target in (targets.minfo, targets.skeleton, *targets.mmeshes):
            if target is None:
                continue
            box.label(text=str(target.relative_to(targets.workspace_root)), icon="FILE")
        box.label(text="不会写入 build；minfo 由 v2 构建器直接生成", icon="INFO")

    def execute(self, context):
        from .gbfr_session import active_session_collection, active_session_root
        collection = active_session_collection(context)
        root = active_session_root(context)
        if collection is None or root is None:
            self.report({"ERROR"}, "请先激活一个 minfo 工作区")
            return {"CANCELLED"}

        state = collection.gbfr_session
        export_scene = None
        original_scene = context.window.scene
        try:
            targets = resolve_model_export_targets(self.filepath, state.model_id)
            export_scene = bpy.data.scenes.new(name=f"GBFR Export | {state.model_id}")
            export_collection = bpy.data.collections.new(name="Model")
            export_scene.collection.children.link(export_collection)
            export_root = _duplicate_hierarchy(root, export_collection)
            context.window.scene = export_scene
            context.view_layer.objects.active = export_root
            export_root.select_set(True)

            with tempfile.TemporaryDirectory(prefix=f"gbfr_v2_{targets.model_id}_") as staging:
                staging_root = Path(staging)
                gbfr_model_export_v2.write_some_data(
                    context,
                    str(staging_root / f"{targets.model_id}.minfo"),
                    self.export_scale,
                    True,
                )
                _install_workspace_export(staging_root, targets)

            state.workspace_path = str(targets.workspace_json)
            state.resolved_minfo_path = str(targets.minfo)
            state.last_status = "全部 LOD 已导出到 unpack"
            self.report({"INFO"}, f"已导出到 {targets.workspace_root / 'unpack'}")
            return {"FINISHED"}
        except Exception as error:
            state.last_status = f"模型导出失败: {error}"
            self.report({"ERROR"}, state.last_status)
            return {"CANCELLED"}
        finally:
            context.window.scene = original_scene
            if export_scene is not None:
                bpy.data.scenes.remove(export_scene)


def menu_func_export(self, _context):
    self.layout.operator(ExportSomeData.bl_idname, text="Granblue Fantasy Relink 工作区")


def register():
    bpy.utils.register_class(ExportSomeData)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.utils.unregister_class(ExportSomeData)
