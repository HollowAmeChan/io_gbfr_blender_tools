"""Export v2 model hierarchies into a GBFR Modtools workspace."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from . import gbfr_model_export_v2
from .Entities.ModelSkeleton import ModelSkeleton
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


def _stream_level(name):
    lowered = name.casefold()
    for index in range(3):
        level = f"shadowlod{index}"
        if level in lowered:
            return level
    for index in range(5):
        level = f"lod{index}"
        if level in lowered:
            return level
    return None


def _duplicate_lod(source, parent, collection, name):
    mapping = {}
    for source_object in _hierarchy(source):
        duplicate = source_object.copy()
        if source_object.data is not None:
            duplicate.data = source_object.data.copy()
        collection.objects.link(duplicate)
        mapping[source_object] = duplicate

    for source_object, duplicate in mapping.items():
        duplicate.parent = mapping.get(source_object.parent, parent)
        for modifier in duplicate.modifiers:
            if modifier.type == "ARMATURE" and modifier.object in mapping:
                modifier.object = mapping[modifier.object]
    duplicate_root = mapping[source]
    duplicate_root.name = name
    return duplicate_root


def _fill_missing_regular_lods(root, collection, targets):
    children = {
        level: child
        for child in root.children
        if (level := _stream_level(child.name)) is not None
    }
    source = children.get("lod0")
    if source is None:
        return ()

    created = []
    required = {
        level
        for target in targets.mmeshes
        if (level := _stream_level(target.parent.name)) is not None
        and level.startswith("lod")
    }
    for index in range(1, 5):
        level = f"lod{index}"
        if level in required and level not in children:
            children[level] = _duplicate_lod(source, root, collection, level)
            created.append(level)
    return tuple(created)


def _atomic_install(source, target, temporary_files):
    if not source.is_file():
        raise FileNotFoundError(f"导出结果缺失: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".gbfr-export.tmp")
    shutil.copy2(source, temporary)
    temporary_files.append((temporary, target))


def _install_workspace_export(staging_root, targets, extra_files=()):
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
    files.extend(extra_files)

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


def _validate_skeleton_contract(root, reference_path, preserve_reference_skeleton=False):
    if reference_path is None:
        return
    if root.type != "ARMATURE":
        raise RuntimeError("源资源包含 skeleton，但当前导出根对象不是骨架")

    reference = ModelSkeleton.GetRootAs(bytearray(Path(reference_path).read_bytes()), 0)
    if preserve_reference_skeleton:
        reference_names = {
            reference.Body(index).Name().decode("utf-8")
            for index in range(reference.BodyLength())
        }
        missing_groups = set()
        for lod_object in root.children:
            for mesh_object in lod_object.children:
                if mesh_object.type != "MESH":
                    continue
                for vertex in mesh_object.data.vertices:
                    for influence in vertex.groups:
                        if influence.weight <= 0.0 or influence.group >= len(mesh_object.vertex_groups):
                            continue
                        group_name = mesh_object.vertex_groups[influence.group].name
                        if group_name not in reference_names:
                            missing_groups.add(group_name)
        if missing_groups:
            detail = ", ".join(sorted(missing_groups)[:8])
            raise RuntimeError(f"FP 头部存在 source skeleton 未定义的加权顶点组: {detail}")
        return

    current_bones = gbfr_model_export_v2.ordered_export_bones(root, reference)
    current_index_by_name = {bone.name: index for index, bone in enumerate(current_bones)}
    problems = []
    if len(current_bones) < reference.BodyLength():
        problems.append(f"骨骼数量 {len(current_bones)} 少于源骨架 {reference.BodyLength()}")

    for index in range(min(len(current_bones), reference.BodyLength())):
        source_bone = reference.Body(index)
        source_name = source_bone.Name().decode("utf-8")
        current_bone = current_bones[index]
        current_name = gbfr_model_export_v2.export_bone_name(current_bone)
        current_parent = current_index_by_name[current_bone.parent.name] if current_bone.parent else 65535
        if current_name != source_name:
            problems.append(f"索引 {index}: 源骨骼 {source_name}，当前为 {current_name}")
        if current_parent != source_bone.ParentId():
            problems.append(
                f"索引 {index} ({source_name}): 源父索引 {source_bone.ParentId()}，当前为 {current_parent}"
            )
        if len(problems) >= 8:
            break

    if problems:
        detail = "；".join(problems)
        raise RuntimeError(
            "骨架索引契约已改变，cloth/SOP/动作可能引用错误骨骼。"
            f"请恢复源骨骼及顺序，或关闭“严格检查源骨架”后继续实验。详情：{detail}"
        )


def _draw_clp_numeric_name_warnings(layout, armature):
    if armature is None:
        return {}
    from .gbfr_cloth_blender import clp_numeric_name_reference_groups
    warnings = clp_numeric_name_reference_groups(armature)
    if not warnings:
        return warnings

    warning = layout.box()
    warning.alert = True
    warning.label(
        text=f"CLP 引用了 {len(warnings)} 根纯数字区骨骼（_000-_999）",
        icon="ERROR",
    )
    warning.label(text="纯数字区通常包含 Root、身体或其他动画主骨，请逐项确认")
    names_by_group = {}
    for name, group_ids in warnings.items():
        for group_id in group_ids:
            names_by_group.setdefault(group_id, []).append(name)
    for group_id in sorted(names_by_group):
        names = sorted(names_by_group[group_id])
        for offset in range(0, len(names), 8):
            prefix = f"CLP {group_id}: " if offset == 0 else ""
            warning.label(text=prefix + ", ".join(names[offset:offset + 8]))
    return warnings


class ExportSomeData(Operator, ImportHelper):
    """Export the active minfo session to workspace unpack."""

    bl_idname = "gbfr.export_mesh"
    bl_label = "导出到 GBFR 工作区"
    bl_description = "选择 workspace.json，将当前模型的全部 LOD 覆盖到 unpack"

    filename_ext = ".json"
    filter_glob: StringProperty(default="workspace.json;*.json", options={"HIDDEN"}, maxlen=255)
    export_scale: FloatProperty(name="导出缩放", default=1.0)
    fill_missing_lods: BoolProperty(
        name="用 LOD0 补齐缺失 LOD",
        description="导出时用最高精度 lod0 生成工作区要求但当前模型中缺少的 lod1-lod4；不会修改 Blender 场景",
        default=True,
    )
    strict_skeleton_contract: BoolProperty(
        name="严格检查源骨架",
        description="阻止删除、重排或改父级后的源骨架导出；排查 cloth、SOP、动作引用时启用",
        default=True,
    )
    experimental_rename_new_bones: BoolProperty(
        name="实验：新增骨骼使用白名单编号",
        description="仅在临时导出副本中，将新增骨骼和对应顶点组按纯数字 _xxx、_cxx、_axx、_dxx 的优先级改名；不改变父子关系和原骨骼顺序",
        default=True,
    )

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
        layout.prop(self, "fill_missing_lods")
        layout.prop(self, "strict_skeleton_contract")
        layout.prop(self, "experimental_rename_new_bones")
        from .gbfr_session import active_session_armature, active_session_collection
        collection = active_session_collection(context)
        box = layout.box()
        if collection is None:
            box.label(text="没有激活的 minfo 工作区", icon="ERROR")
            return
        state = collection.gbfr_session
        box.label(text=f"当前模型: {state.model_id}", icon="FILE_3D")
        _draw_clp_numeric_name_warnings(layout, active_session_armature(context))
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
        if targets.reference_skeleton is not None:
            if targets.model_id.lower().startswith("fp"):
                box.label(text="FP 头部直接保留 source skeleton；Blender 缺失的非蒙皮占位骨不会阻止导出", icon="LOCKED")
            else:
                box.label(text="源骨骼索引保持不变；融合新增骨骼统一追加到末尾", icon="LOCKED")
        if self.experimental_rename_new_bones:
            box.label(text="实验模式：白名单优先 _xxx → _cxx → _axx → _dxx，只改名不改父子关系", icon="INFO")
        if self.fill_missing_lods:
            box.label(text="缺失的低精度 LOD 将在导出时使用 LOD0", icon="DUPLICATE")
        cloth_state = getattr(active_session_armature(context), "gbfr_cloth", None)
        if cloth_state is not None and cloth_state.enabled:
            box.label(text="当前会话的全部 CLP/CLH 将同时写入 unpack XML", icon="PHYSICS")
        else:
            box.label(text="当前模型未登记 CLP/CLH，不会写入 cloth", icon="INFO")

    def execute(self, context):
        from .gbfr_session import active_session_armature, active_session_collection, active_session_root
        collection = active_session_collection(context)
        root = active_session_root(context)
        cloth_armature = active_session_armature(context)
        if collection is None or root is None:
            self.report({"ERROR"}, "请先激活一个 minfo 工作区")
            return {"CANCELLED"}

        state = collection.gbfr_session
        export_scene = None
        original_scene = context.window.scene
        try:
            targets = resolve_model_export_targets(self.filepath, state.model_id)
            if self.strict_skeleton_contract:
                _validate_skeleton_contract(
                    root,
                    targets.reference_skeleton,
                    preserve_reference_skeleton=targets.model_id.lower().startswith("fp"),
                )
            cloth_repairs = (0, 0, 0)
            if cloth_armature is not None:
                from .gbfr_cloth_blender import prepare_cloth_for_model_export
                cloth_repairs = prepare_cloth_for_model_export(
                    cloth_armature, targets.minfo, targets.workspace_json,
                )
            export_scene = bpy.data.scenes.new(name=f"GBFR Export | {state.model_id}")
            export_collection = bpy.data.collections.new(name="Model")
            export_scene.collection.children.link(export_collection)
            export_root = _duplicate_hierarchy(root, export_collection)
            context.window.scene = export_scene
            context.view_layer.objects.active = export_root
            exported_bone_names = {}
            export_root.select_set(True)

            filled_lods = ()
            if self.fill_missing_lods:
                filled_lods = _fill_missing_regular_lods(export_root, export_collection, targets)

            cloth_count = 0
            with tempfile.TemporaryDirectory(prefix=f"gbfr_v2_{targets.model_id}_") as staging:
                staging_root = Path(staging)
                exported_bone_names = gbfr_model_export_v2.write_some_data(
                    context,
                    str(staging_root / f"{targets.model_id}.minfo"),
                    self.export_scale,
                    True,
                    reference_skeleton_path=targets.reference_skeleton,
                    experimental_rename_new_bones=self.experimental_rename_new_bones,
                    preserve_reference_skeleton=targets.model_id.lower().startswith("fp"),
                )
                staged_cloth = ()
                if cloth_armature is not None:
                    from .gbfr_cloth_blender import stage_cloth_xml_for_workspace
                    staged_cloth = stage_cloth_xml_for_workspace(
                        cloth_armature, targets.minfo, targets.workspace_json,
                        staging_root / "cloth", exported_bone_names,
                    )
                _install_workspace_export(
                    staging_root, targets, extra_files=staged_cloth,
                )
                cloth_count = len(staged_cloth)

            state.workspace_path = str(targets.workspace_json)
            state.resolved_minfo_path = str(targets.minfo)
            pinned, migrated, deduplicated = cloth_repairs
            repair_detail = ""
            if pinned or migrated or deduplicated:
                repair_detail = (
                    f"；Cloth 骨号修复 {pinned}，引用迁移 {migrated}，重复节点合并 {deduplicated}"
                )
            if filled_lods:
                state.last_status = f"已导出模型和 {cloth_count} 个 Cloth XML 到 unpack；LOD0 补齐 {', '.join(filled_lods)}{repair_detail}"
            else:
                state.last_status = f"已导出全部 LOD 和 {cloth_count} 个 Cloth XML 到 unpack{repair_detail}"
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
