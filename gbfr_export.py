"""Export v2 model hierarchies into a GBFR Modtools workspace."""

from __future__ import annotations

import math
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


def _validate_skeleton_contract(root, reference_path, preserve_missing_reference_bones=False):
    if reference_path is None:
        return
    if root.type != "ARMATURE":
        raise RuntimeError("源资源包含 skeleton，但当前导出根对象不是骨架")

    reference = ModelSkeleton.GetRootAs(bytearray(Path(reference_path).read_bytes()), 0)
    reference_index_by_name = {
        reference.Body(index).Name().decode("utf-8"): index
        for index in range(reference.BodyLength())
    }
    current_by_export_name = {}
    problems = []
    for bone in root.data.bones:
        export_name = gbfr_model_export_v2.export_bone_name(bone)
        previous = current_by_export_name.get(export_name)
        if previous is not None:
            problems.append(f"导出骨骼名重复: {previous.name} / {bone.name} -> {export_name}")
        else:
            current_by_export_name[export_name] = bone

    for index in range(reference.BodyLength()):
        source_bone = reference.Body(index)
        source_name = source_bone.Name().decode("utf-8")
        current_bone = current_by_export_name.get(source_name)
        if current_bone is None:
            if not preserve_missing_reference_bones:
                problems.append(f"缺少源骨骼: 索引 {index} {source_name}")
            continue
        if current_bone.parent is None:
            current_parent = 65535
        else:
            current_parent_name = gbfr_model_export_v2.export_bone_name(current_bone.parent)
            current_parent = reference_index_by_name.get(current_parent_name, -1)
        if current_parent != source_bone.ParentId():
            problems.append(
                f"索引 {index} ({source_name}): 源父索引 {source_bone.ParentId()}，当前为 {current_parent}"
            )
        if len(problems) >= 8:
            break

    missing_weight_bones = set()
    for lod_object in root.children:
        for mesh_object in lod_object.children:
            if mesh_object.type != "MESH":
                continue
            for vertex in mesh_object.data.vertices:
                for influence in vertex.groups:
                    if influence.weight <= 0.0 or influence.group >= len(mesh_object.vertex_groups):
                        continue
                    group_name = mesh_object.vertex_groups[influence.group].name
                    if root.data.bones.get(group_name) is None:
                        missing_weight_bones.add(group_name)
    if missing_weight_bones:
        detail = ", ".join(sorted(missing_weight_bones)[:8])
        problems.append(f"加权顶点组没有真实骨骼对象: {detail}")

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


def inspect_export_weights(root, normalization_tolerance=1e-6, max_influences=4):
    """Inspect positive vertex weights in the hierarchy exported by v2."""
    details = []
    total_vertices = 0
    unnormalized_total = 0
    over_limit_total = 0
    meshes = [obj for obj in _hierarchy(root) if obj.type == "MESH"] if root else []
    for mesh_object in meshes:
        unnormalized = 0
        over_limit = 0
        for vertex in mesh_object.data.vertices:
            positive_weights = [
                influence.weight
                for influence in vertex.groups
                if influence.weight > 0.0
            ]
            if not math.isclose(
                sum(positive_weights), 1.0,
                rel_tol=0.0, abs_tol=normalization_tolerance,
            ):
                unnormalized += 1
            if len(positive_weights) > max_influences:
                over_limit += 1
        total_vertices += len(mesh_object.data.vertices)
        unnormalized_total += unnormalized
        over_limit_total += over_limit
        if unnormalized or over_limit:
            details.append((mesh_object.name, unnormalized, over_limit))
    return {
        "mesh_count": len(meshes),
        "vertex_count": total_vertices,
        "unnormalized": unnormalized_total,
        "over_limit": over_limit_total,
        "details": tuple(details),
    }


def _run_export_weight_check(context):
    from .gbfr_session import active_session_collection, active_session_root
    collection = active_session_collection(context)
    root = active_session_root(context)
    if collection is None or root is None:
        return None
    result = inspect_export_weights(root)
    state = collection.gbfr_session
    state.weight_check_completed = True
    state.weight_check_unnormalized = result["unnormalized"]
    state.weight_check_over_four = result["over_limit"]
    state.weight_check_meshes = result["mesh_count"]
    state.weight_check_details = "\n".join(
        f"{name}: 未归一化 {unnormalized}，超过 4 组 {over_limit}"
        for name, unnormalized, over_limit in result["details"]
    )
    return result


def _draw_export_weight_check(layout, state):
    box = layout.box()
    row = box.row(align=True)
    row.label(text="顶点权重检查", icon="GROUP_VERTEX")
    row.operator(GBFR_OT_CheckExportWeights.bl_idname, text="重新检查", icon="FILE_REFRESH")
    if not state.weight_check_completed:
        box.label(text="尚未检查", icon="INFO")
        return
    has_errors = state.weight_check_unnormalized or state.weight_check_over_four
    if has_errors:
        box.alert = True
        if state.weight_check_unnormalized:
            box.label(
                text=f"未归一化顶点: {state.weight_check_unnormalized}",
                icon="ERROR",
            )
        if state.weight_check_over_four:
            box.label(
                text=f"正权重组超过 4 的顶点: {state.weight_check_over_four}",
                icon="ERROR",
            )
        for detail in state.weight_check_details.splitlines():
            box.label(text=detail)
    else:
        box.label(
            text=f"通过：{state.weight_check_meshes} 个 Mesh 均已归一化且不超过 4 组",
            icon="CHECKMARK",
        )


class GBFR_OT_CheckExportWeights(Operator):
    bl_idname = "gbfr.check_export_weights"
    bl_label = "检查导出权重"
    bl_description = "检查未归一化顶点和正权重组超过 4 的顶点"

    def execute(self, context):
        result = _run_export_weight_check(context)
        if result is None:
            self.report({"ERROR"}, "请先激活一个 minfo 工作区")
            return {"CANCELLED"}
        issues = result["unnormalized"] + result["over_limit"]
        if issues:
            self.report(
                {"WARNING"},
                f"未归一化 {result['unnormalized']}，超过 4 组 {result['over_limit']}",
            )
        else:
            self.report({"INFO"}, f"权重检查通过，共 {result['vertex_count']} 个顶点")
        return {"FINISHED"}


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
        description="仅在临时导出副本中，将新增骨骼和对应顶点组按 _cxx、_axx、_dxx、纯数字 _xxx 的优先级改名；source 原骨与已知 FP 面骨号保持不变",
        default=True,
    )

    def invoke(self, context, _event):
        from .gbfr_session import active_session_collection
        collection = active_session_collection(context)
        if collection is not None and collection.gbfr_session.workspace_path:
            self.filepath = collection.gbfr_session.workspace_path
        _run_export_weight_check(context)
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
        _draw_export_weight_check(layout, state)
        _draw_clp_numeric_name_warnings(layout, active_session_armature(context))
        try:
            targets = resolve_model_export_targets(self.filepath, state.model_id)
        except Exception as error:
            box.alert = True
            box.label(text=str(error), icon="ERROR")
            return
        box.label(text="将覆盖以下 unpack 文件", icon="EXPORT")
        for target in (targets.minfo, targets.skeleton, *targets.mmeshes, targets.sop):
            if target is None:
                continue
            box.label(text=str(target.relative_to(targets.workspace_root)), icon="FILE")
        box.label(text="不会写入 build；minfo 由 v2 构建器直接生成", icon="INFO")
        if targets.reference_skeleton is not None:
            if targets.model_id.lower().startswith("fp"):
                box.label(text="FP 保留 source 骨号与缺失占位槽；当前 Blender rest 位置/旋转会写入", icon="LOCKED")
            else:
                box.label(text="源骨骼索引保持不变；融合新增骨骼统一追加到末尾", icon="LOCKED")
        if self.experimental_rename_new_bones:
            box.label(text="实验模式：优先 _cxx → _axx → _dxx → 数字区；保留 source 原骨和 FP 面骨号", icon="INFO")
        if self.fill_missing_lods:
            box.label(text="缺失的低精度 LOD 将在导出时使用 LOD0", icon="DUPLICATE")
        cloth_state = getattr(active_session_armature(context), "gbfr_cloth", None)
        if cloth_state is not None and cloth_state.enabled:
            box.label(text="当前会话的全部 CLP/CLH 将同时写入 unpack XML", icon="PHYSICS")
        else:
            box.label(text="当前模型未登记 CLP/CLH，不会写入 cloth", icon="INFO")
        sop_state = getattr(active_session_armature(context), "gbfr_sop", None)
        if targets.sop is not None and sop_state is not None and sop_state.enabled:
            box.label(text="当前 Blender 内的 SOP 编辑将同时写入 unpack", icon="CONSTRAINT")
        elif targets.sop_source is not None:
            box.label(text="source SOP 将随主体复制到 unpack", icon="CONSTRAINT")

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
                    preserve_missing_reference_bones=targets.model_id.lower().startswith("fp"),
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
            sop_count = 0
            with tempfile.TemporaryDirectory(prefix=f"gbfr_v2_{targets.model_id}_") as staging:
                staging_root = Path(staging)
                exported_bone_names = gbfr_model_export_v2.write_some_data(
                    context,
                    str(staging_root / f"{targets.model_id}.minfo"),
                    self.export_scale,
                    True,
                    reference_skeleton_path=targets.reference_skeleton,
                    experimental_rename_new_bones=self.experimental_rename_new_bones,
                    preserve_missing_reference_bones=targets.model_id.lower().startswith("fp"),
                )
                staged_cloth = ()
                if cloth_armature is not None:
                    from .gbfr_cloth_blender import stage_cloth_xml_for_workspace
                    staged_cloth = stage_cloth_xml_for_workspace(
                        cloth_armature, targets.minfo, targets.workspace_json,
                        staging_root / "cloth", exported_bone_names,
                    )
                staged_sop = ()
                if targets.sop is not None:
                    sop_staging = staging_root / "sop" / targets.sop.name
                    sop_staging.parent.mkdir(parents=True, exist_ok=True)
                    sop_state = getattr(cloth_armature, "gbfr_sop", None) if cloth_armature is not None else None
                    if sop_state is not None and sop_state.enabled:
                        from .gbfr_sop_blender import stage_sop_for_workspace
                        stage_sop_for_workspace(cloth_armature, sop_staging)
                    elif targets.sop_source is not None:
                        shutil.copy2(targets.sop_source, sop_staging)
                    if sop_staging.is_file():
                        staged_sop = ((sop_staging, targets.sop),)
                _install_workspace_export(
                    staging_root, targets, extra_files=(*staged_cloth, *staged_sop),
                )
                cloth_count = len(staged_cloth)
                sop_count = len(staged_sop)

            state.workspace_path = str(targets.workspace_json)
            state.resolved_minfo_path = str(targets.minfo)
            if sop_count and cloth_armature is not None and getattr(cloth_armature, "gbfr_sop", None) is not None:
                from .gbfr_sop_blender import populate_sop_state
                from .gbfr_workspace import resolve_model_bundle
                populate_sop_state(
                    cloth_armature,
                    resolve_model_bundle(targets.minfo, targets.workspace_json),
                )
            pinned, migrated, deduplicated = cloth_repairs
            repair_detail = ""
            if pinned or migrated or deduplicated:
                repair_detail = (
                    f"；Cloth 骨号修复 {pinned}，引用迁移 {migrated}，重复节点合并 {deduplicated}"
                )
            if filled_lods:
                state.last_status = f"已导出模型、{cloth_count} 个 Cloth XML 和 {sop_count} 个 SOP 到 unpack；LOD0 补齐 {', '.join(filled_lods)}{repair_detail}"
            else:
                state.last_status = f"已导出全部 LOD、{cloth_count} 个 Cloth XML 和 {sop_count} 个 SOP 到 unpack{repair_detail}"
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
    bpy.utils.register_class(GBFR_OT_CheckExportWeights)
    bpy.utils.register_class(ExportSomeData)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.utils.unregister_class(ExportSomeData)
    bpy.utils.unregister_class(GBFR_OT_CheckExportWeights)
