"""Editable SOP import, guarded Blender preview, and unpack persistence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import bpy
from mathutils import Euler, Quaternion, Vector
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
    IntProperty, PointerProperty, StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, UIList

from .gbfr_sop import (
    OFFSET_X_PROPERTY, OFFSET_Y_PROPERTY, OFFSET_Z_PROPERTY, SOP_VERSION,
    SWING_RATE_PROPERTY, SWING_TWIST_OPERATION, TWIST_RATE_PROPERTY,
    SopAsset, SopDescription, SopOperation, SopProperty, dominant_axis,
    evaluate_core_operation, guarded_preview_status, is_editable_swing_twist,
    load_catalog, load_sop, make_swing_twist_operation, save_sop,
    update_swing_twist_operation,
)
from .gbfr_workspace import ModelBundle
from .gbfr_session import (
    active_session_armature, active_session_collection, resolve_session_bundle,
)
from .utils import bone_names_mapping


CONSTRAINT_PREFIX = "GBFR SOP "
STATUS_LABELS = {
    "approximate_constraint": "已创建 Blender 近似约束",
    "approximate_unchecked": "已创建 Blender 近似约束（无静止姿态基线）",
    "rest_guard_failed": "静止姿态自检失败，未执行",
    "not_implemented": "公式未探明，只读导入",
    "missing_bone": "引用骨骼缺失，未执行",
    "invalid_core_fields": "核心字段不完整，未执行",
}
AXIS_ITEMS = (
    ("0", "X", "X 轴为 Twist 主轴"),
    ("1", "Y", "Y 轴为 Twist 主轴"),
    ("2", "Z", "Z 轴为 Twist 主轴"),
)
OPERATION_FILTER_ITEMS = (
    ("ALL", "全部", "显示全部 SOP 操作"),
    ("EDITABLE", "可编辑", "只显示已探明并可编辑的复制旋转操作"),
    ("READ_ONLY", "只读", "只显示尚未完整探明的只读操作"),
)
NEW_OPERATION_TYPE_ITEMS = (
    (
        "SKIRT_COPY_ROTATION", "裙骨复制旋转",
        "已探明的 Swing/Twist 复制旋转约束",
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bone_map(armature):
    result = {}
    for bone in armature.data.bones:
        value = bone.get("gbfr_bone_id")
        if value is not None and int(value) >= 0:
            result[int(value)] = bone.name
    return result


def _bone_id(armature, bone_name: str) -> int:
    bone = armature.data.bones.get(bone_name)
    if bone is None or bone.get("gbfr_bone_id") is None:
        raise ValueError(f"骨骼没有有效 GBFR ID: {bone_name or '未选择'}")
    value = int(bone["gbfr_bone_id"])
    if value < 0:
        raise ValueError(f"骨骼没有有效 GBFR ID: {bone_name}")
    return value


def _display_bone(bone_id, mapping):
    code = f"_{bone_id:03x}"
    friendly = bone_names_mapping.get(code)
    if friendly:
        return f"{friendly[0]} ({code})"
    return mapping.get(bone_id, code)


def _rest_quaternions(armature):
    result = {}
    for bone in armature.data.bones:
        bone_id = bone.get("gbfr_bone_id")
        value = bone.get("gbfr_rest_quaternion")
        if bone_id is not None and int(bone_id) >= 0 and value is not None and len(value) == 4:
            result[int(bone_id)] = tuple(float(component) for component in value)
    return result


def _export_rest_quaternion(armature, bone_name: str) -> Quaternion:
    bone = armature.data.bones.get(bone_name)
    if bone is None:
        raise ValueError(f"骨骼不存在: {bone_name or '未选择'}")
    matrix = bone.matrix_local.copy()
    if bone.parent is not None:
        matrix = bone.parent.matrix_local.inverted() @ matrix
    return matrix.to_quaternion().normalized()


def _require_parallel_bones(armature, target_name: str, source_name: str) -> None:
    target = armature.data.bones.get(target_name)
    source = armature.data.bones.get(source_name)
    if target is None or source is None:
        raise ValueError("SOP 目标骨或来源骨不存在")
    target_parent = target.parent.name if target.parent is not None else ""
    source_parent = source.parent.name if source.parent is not None else ""
    if target_parent != source_parent:
        raise ValueError(
            "裙骨复制旋转要求目标骨与来源骨具有同一父级；"
            f"当前为 {target_parent or '无父级'} / {source_parent or '无父级'}"
        )


def _operation_offset_quaternion(operation: SopOperation) -> Quaternion:
    values = tuple(
        operation.floating(property_hash, 0.0) or 0.0
        for property_hash in (OFFSET_X_PROPERTY, OFFSET_Y_PROPERTY, OFFSET_Z_PROPERTY)
    )
    return Euler(values, "XYZ").to_quaternion().normalized()


def _fit_operation_rest_offset(
    armature, operation: SopOperation, target_name: str, source_name: str,
) -> SopOperation:
    _require_parallel_bones(armature, target_name, source_name)
    zero_offset = update_swing_twist_operation(
        operation,
        target_bone=operation.target_bone,
        source_bone=operation.source_bone,
        axis=dominant_axis(operation),
        swing_rate=operation.floating(SWING_RATE_PROPERTY, 0.0) or 0.0,
        twist_rate=operation.floating(TWIST_RATE_PROPERTY, 0.0) or 0.0,
        offset_xyz=(0.0, 0.0, 0.0),
    )
    source_rest = _export_rest_quaternion(armature, source_name)
    target_rest = _export_rest_quaternion(armature, target_name)
    base_value = evaluate_core_operation(zero_offset, tuple(source_rest))
    if base_value is None:
        raise ValueError("无法计算裙骨复制旋转的静止姿态")
    offset = Quaternion(base_value).normalized().inverted() @ target_rest
    offset_xyz = tuple(float(value) for value in offset.to_euler("XYZ"))
    return update_swing_twist_operation(
        zero_offset,
        target_bone=operation.target_bone,
        source_bone=operation.source_bone,
        axis=dominant_axis(operation),
        swing_rate=operation.floating(SWING_RATE_PROPERTY, 0.0) or 0.0,
        twist_rate=operation.floating(TWIST_RATE_PROPERTY, 0.0) or 0.0,
        offset_xyz=offset_xyz,
    )


def _blender_preview_status(operation, mapping, rest_quaternions):
    status = guarded_preview_status(operation, rest_quaternions)
    if (
        status == "missing_bone"
        and operation.target_bone in mapping
        and operation.source_bone in mapping
        and is_editable_swing_twist(operation)
    ):
        return "approximate_unchecked"
    return status


def _remove_imported_constraints(armature):
    for pose_bone in armature.pose.bones:
        for constraint in tuple(pose_bone.constraints):
            if constraint.name.startswith(CONSTRAINT_PREFIX):
                pose_bone.constraints.remove(constraint)


def _set_constraints_enabled(armature, enabled):
    for pose_bone in armature.pose.bones:
        for constraint in pose_bone.constraints:
            if constraint.name.startswith(CONSTRAINT_PREFIX):
                constraint.mute = not enabled


def _preview_update(state, _context):
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and hasattr(obj, "gbfr_sop") and obj.gbfr_sop.as_pointer() == state.as_pointer():
            _set_constraints_enabled(obj, state.preview_constraints)
            break


def _operation_owner(item):
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE" or not hasattr(obj, "gbfr_sop"):
            continue
        state = obj.gbfr_sop
        if any(value.as_pointer() == item.as_pointer() for value in state.operations):
            return obj, state
    return None, None


def _operation_edit_update(item, _context):
    armature, state = _operation_owner(item)
    if state is None or state.suspend_updates:
        return
    item.target_name = item.target_ref or item.target_name
    item.source_name = item.source_ref or item.source_name
    state.dirty = True
    rebuild_sop_preview(armature)


class GBFRSopOperationProperties(PropertyGroup):
    operation_index: IntProperty(name="原文件序号", default=-1)
    editable: BoolProperty(default=False)
    auto_rest_offset: BoolProperty(default=False)
    target_bone: IntProperty(name="Target", default=-1)
    source_bone: IntProperty(name="Source", default=-1)
    target_name: StringProperty(name="Target")
    source_name: StringProperty(name="Source")
    target_ref: StringProperty(name="目标骨", update=_operation_edit_update)
    source_ref: StringProperty(name="来源骨", update=_operation_edit_update)
    axis: EnumProperty(name="旋转轴", items=AXIS_ITEMS, default="1", update=_operation_edit_update)
    swing_rate: FloatProperty(
        name="Swing 比例", default=0.5, min=-2.0, max=2.0, soft_min=0.0, soft_max=1.0,
        update=_operation_edit_update,
    )
    twist_rate: FloatProperty(
        name="Twist 比例", default=0.0, min=-2.0, max=2.0, soft_min=0.0, soft_max=1.0,
        update=_operation_edit_update,
    )
    type_hash: StringProperty(name="类型哈希")
    operation_name: StringProperty(name="操作")
    category: StringProperty(name="类别")
    discovery: StringProperty(name="探明状态")
    discovery_label: StringProperty(name="探明状态")
    runtime_label: StringProperty(name="Modtools 状态")
    preview_status: StringProperty(name="Blender 状态")
    purpose: StringProperty(name="作用")
    metadata: StringProperty(name="Metadata")
    properties_json: StringProperty(name="原始属性")


class GBFRSopStateProperties(PropertyGroup):
    enabled: BoolProperty(default=False)
    source_path: StringProperty(name="当前 SOP", subtype="FILE_PATH")
    source_baseline_path: StringProperty(name="source SOP", subtype="FILE_PATH")
    edit_path: StringProperty(name="unpack SOP", subtype="FILE_PATH")
    source_sha256: StringProperty()
    minfo_path: StringProperty(name="minfo", subtype="FILE_PATH")
    version: StringProperty(name="版本")
    operations: CollectionProperty(type=GBFRSopOperationProperties)
    active_operation_index: IntProperty(default=0)
    operation_filter: EnumProperty(
        name="列表筛选", items=OPERATION_FILTER_ITEMS, default="ALL",
    )
    operation_search: StringProperty(name="搜索约束")
    preview_constraints: BoolProperty(
        name="启用核心约束近似预览", default=True, update=_preview_update,
        description="只启用通过静止姿态自检的 Swing/Twist 近似；属性修改只作用于 Blender 内存",
    )
    imported_constraint_count: IntProperty(default=0)
    preview_operation_count: IntProperty(default=0)
    guarded_count: IntProperty(default=0)
    unresolved_count: IntProperty(default=0)
    missing_count: IntProperty(default=0)
    dirty: BoolProperty(default=False)
    suspend_updates: BoolProperty(default=False)
    last_status: StringProperty()


def _property_json(operation: SopOperation) -> str:
    return json.dumps([
        {
            "hash": f"0x{value.hash:08X}",
            "type": "float" if value.value_type == 1 else "integer",
            "value": value.value,
            "raw": f"0x{value.raw_value:08X}",
        }
        for value in operation.properties
    ], ensure_ascii=False)


def _properties_from_json(value: str) -> tuple[SopProperty, ...]:
    result = []
    for item in json.loads(value):
        value_type = 1 if item.get("type") == "float" else 0
        result.append(SopProperty(int(item["hash"], 0), value_type, int(item["raw"], 0)))
    return tuple(result)


def _populate_item(item, operation, description, status, mapping):
    item.name = f"#{operation.index:03d} {description.name}" if operation.index >= 0 else f"新增 {description.name}"
    item.operation_index = operation.index
    item.editable = is_editable_swing_twist(operation)
    item.auto_rest_offset = status == "approximate_unchecked"
    item.target_bone = operation.target_bone
    item.source_bone = operation.source_bone
    item.target_name = _display_bone(operation.target_bone, mapping)
    item.source_name = _display_bone(operation.source_bone, mapping)
    item.target_ref = mapping.get(operation.target_bone, "")
    item.source_ref = mapping.get(operation.source_bone, "")
    item.type_hash = f"0x{operation.type_hash:08X}"
    item.operation_name = description.name
    item.category = description.category
    item.discovery = description.discovery
    item.discovery_label = description.discovery_label
    item.runtime_label = description.runtime_label
    item.preview_status = status
    item.purpose = description.purpose
    item.metadata = f"0x{operation.metadata:08X}"
    item.properties_json = _property_json(operation)
    if item.editable:
        item.axis = str(dominant_axis(operation) if dominant_axis(operation) is not None else 1)
        item.swing_rate = operation.floating(SWING_RATE_PROPERTY, 0.0) or 0.0
        item.twist_rate = operation.floating(TWIST_RATE_PROPERTY, 0.0) or 0.0


def _operation_from_item(item, armature, index: int) -> SopOperation:
    operation = SopOperation(
        index=index,
        type_hash=int(item.type_hash, 0),
        metadata=int(item.metadata, 0),
        target_bone=item.target_bone,
        source_bone=item.source_bone,
        properties=_properties_from_json(item.properties_json),
    )
    if not item.editable:
        return operation
    target = _bone_id(armature, item.target_ref)
    source = _bone_id(armature, item.source_ref)
    if target == source:
        raise ValueError("SOP 目标骨和来源骨不能相同")
    operation = update_swing_twist_operation(
        operation,
        target_bone=target,
        source_bone=source,
        axis=int(item.axis),
        swing_rate=item.swing_rate,
        twist_rate=item.twist_rate,
    )
    target_data = armature.data.bones.get(item.target_ref)
    needs_auto_rest_offset = item.auto_rest_offset or (
        target_data is not None and target_data.get("gbfr_rest_quaternion") is None
    )
    if needs_auto_rest_offset:
        operation = _fit_operation_rest_offset(
            armature, operation, item.target_ref, item.source_ref,
        )
    return operation


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve().samefile(right.resolve())
    except (FileNotFoundError, OSError):
        return str(left.resolve()).casefold() == str(right.resolve()).casefold()


def _asset_from_state(armature) -> SopAsset:
    state = armature.gbfr_sop
    operations = tuple(
        _operation_from_item(item, armature, index)
        for index, item in enumerate(state.operations)
    )
    return SopAsset(Path(state.edit_path), SOP_VERSION, operations)


def _validate_loaded_sop_unchanged(state) -> None:
    source = Path(state.source_path)
    if source.is_file() and _sha256(source) != state.source_sha256:
        raise ValueError("SOP 文件已被外部修改，请先重新导入")


def stage_sop_for_workspace(armature, staging_path: str | Path) -> Path:
    state = getattr(armature, "gbfr_sop", None)
    if state is None or not state.enabled:
        raise ValueError("当前骨架没有可导出的 SOP")
    _validate_loaded_sop_unchanged(state)
    return save_sop(staging_path, _asset_from_state(armature))


def export_sop_to_unpack(armature) -> Path:
    state = armature.gbfr_sop
    _validate_loaded_sop_unchanged(state)
    source = Path(state.source_path)
    target = Path(state.edit_path)
    if target.is_file() and not _same_path(target, source):
        raise ValueError("unpack SOP 在导入后出现，请重新导入以避免覆盖")
    return save_sop(target, _asset_from_state(armature))


def _model_export_ready(context, state) -> bool:
    collection = active_session_collection(context)
    if collection is None:
        return False
    resolved_path = collection.gbfr_session.resolved_minfo_path.strip()
    edit_path = state.edit_path.strip()
    if not resolved_path or not edit_path:
        return False
    resolved = Path(resolved_path)
    expected = Path(edit_path).with_suffix(".minfo")
    return resolved.is_file() and expected.is_file() and _same_path(resolved, expected)


def _active_sop_bundle(context) -> ModelBundle:
    return resolve_session_bundle(
        active_session_collection(context), require_cloth_xml=False,
    )


def _sync_workspace_paths(state, bundle: ModelBundle) -> None:
    state.minfo_path = str(bundle.minfo)
    state.edit_path = str(bundle.sop_edit)
    state.source_baseline_path = str(bundle.sop_source or "")


def _add_copy_rotation(
    armature, target_name, source_name, operation_index, label, axes, rate,
    *, inversions=None, target_space="LOCAL",
):
    target = armature.pose.bones.get(target_name)
    if target is None or source_name not in armature.pose.bones:
        return 0
    constraint = target.constraints.new("COPY_ROTATION")
    constraint.name = f"{CONSTRAINT_PREFIX}#{operation_index:03d} {label} [近似]"
    constraint.target = armature
    constraint.subtarget = source_name
    constraint.target_space = target_space
    constraint.owner_space = "LOCAL"
    constraint.mix_mode = "BEFORE"
    constraint.show_expanded = False
    constraint.use_x, constraint.use_y, constraint.use_z = axes
    if inversions is None:
        inversions = tuple(rate < 0.0 and enabled for enabled in axes)
    constraint.invert_x, constraint.invert_y, constraint.invert_z = inversions
    constraint.influence = min(abs(float(rate)), 1.0)
    return 1


def _mapped_owner_axes(operation: SopOperation, source_axes, rate):
    offset = _operation_offset_quaternion(operation)
    axes = [False, False, False]
    inversions = [False, False, False]
    for source_axis in source_axes:
        vector = Vector(tuple(float(index == source_axis) for index in range(3)))
        mapped = offset.inverted() @ vector
        owner_axis = max(range(3), key=lambda index: abs(mapped[index]))
        if abs(mapped[owner_axis]) < 0.95 or axes[owner_axis]:
            return None
        axes[owner_axis] = True
        inversions[owner_axis] = mapped[owner_axis] * rate < 0.0
    return tuple(axes), tuple(inversions)


def _create_approximate_constraints(armature, operation, mapping):
    axis = dominant_axis(operation)
    target = mapping.get(operation.target_bone)
    source = mapping.get(operation.source_bone)
    if axis is None or target is None or source is None:
        return 0
    twist_rate = operation.floating(TWIST_RATE_PROPERTY)
    if twist_rate is None:
        return 0
    count = 0
    if operation.type_hash == SWING_TWIST_OPERATION:
        swing_rate = operation.floating(SWING_RATE_PROPERTY)
        if swing_rate is None:
            return 0
        if abs(swing_rate) > 1e-8:
            mapped = _mapped_owner_axes(
                operation, tuple(index for index in range(3) if index != axis), swing_rate,
            )
            if mapped is None:
                return 0
            count += _add_copy_rotation(
                armature, target, source, operation.index, "Swing", mapped[0], swing_rate,
                inversions=mapped[1], target_space="LOCAL_OWNER_ORIENT",
            )
    if abs(twist_rate) > 1e-8:
        mapped = _mapped_owner_axes(operation, (axis,), twist_rate)
        if mapped is None:
            return 0
        count += _add_copy_rotation(
            armature, target, source, operation.index, "Twist", mapped[0], twist_rate,
            inversions=mapped[1], target_space="LOCAL_OWNER_ORIENT",
        )
    return count


def rebuild_sop_preview(armature) -> None:
    state = armature.gbfr_sop
    mapping = _bone_map(armature)
    rest = _rest_quaternions(armature)
    _remove_imported_constraints(armature)
    state.imported_constraint_count = 0
    state.preview_operation_count = 0
    state.guarded_count = 0
    state.unresolved_count = 0
    state.missing_count = 0
    for index, item in enumerate(state.operations):
        try:
            operation = _operation_from_item(item, armature, index)
            status = _blender_preview_status(operation, mapping, rest)
        except (ValueError, TypeError, json.JSONDecodeError):
            item.preview_status = "invalid_core_fields"
            state.missing_count += 1
            continue
        item.target_bone = operation.target_bone
        item.source_bone = operation.source_bone
        item.target_name = _display_bone(operation.target_bone, mapping)
        item.source_name = _display_bone(operation.source_bone, mapping)
        item.preview_status = status
        if status in {"approximate_constraint", "approximate_unchecked"}:
            created = _create_approximate_constraints(armature, operation, mapping)
            state.imported_constraint_count += created
            if created:
                state.preview_operation_count += 1
            else:
                item.preview_status = "invalid_core_fields"
                state.missing_count += 1
        elif status == "rest_guard_failed":
            state.guarded_count += 1
        elif status == "not_implemented":
            state.unresolved_count += 1
        else:
            state.missing_count += 1
    _set_constraints_enabled(armature, state.preview_constraints)


def populate_sop_state(
    armature: bpy.types.Object,
    bundle: ModelBundle,
    load_path_override: str | Path | None = None,
) -> None:
    state = armature.gbfr_sop
    state.enabled = False
    state.suspend_updates = True
    state.operations.clear()
    _remove_imported_constraints(armature)
    state.minfo_path = str(bundle.minfo)
    state.edit_path = str(bundle.sop_edit)
    state.source_baseline_path = str(bundle.sop_source or "")
    state.imported_constraint_count = 0
    state.preview_operation_count = 0
    state.guarded_count = 0
    state.unresolved_count = 0
    state.missing_count = 0
    load_path = Path(load_path_override) if load_path_override is not None else (
        bundle.sop_edit if bundle.sop_edit.is_file() else bundle.sop
    )
    # A source restore changes only the in-memory asset. Keep watching the current
    # unpack file so a later explicit export still detects outside modifications.
    watch_path = bundle.sop_edit if bundle.sop_edit.is_file() else load_path
    state.source_path = str(watch_path or "")
    if load_path is None:
        state.source_sha256 = ""
        state.last_status = "工作区中没有找到同模型 SOP"
        state.suspend_updates = False
        return

    asset = load_sop(load_path)
    catalog = load_catalog(Path(__file__).parent / "data" / "sop_operations_zh.json")
    mapping = _bone_map(armature)
    rest = _rest_quaternions(armature)
    state.version = f"0x{asset.version:08X}"
    for operation in asset.operations:
        description = catalog.get(operation.type_hash, SopDescription())
        item = state.operations.add()
        _populate_item(item, operation, description, _blender_preview_status(operation, mapping, rest), mapping)
    state.active_operation_index = min(state.active_operation_index, max(0, len(state.operations) - 1))
    state.source_sha256 = _sha256(watch_path)
    state.enabled = True
    state.dirty = False
    state.suspend_updates = False
    rebuild_sop_preview(armature)
    state.last_status = (
        f"读取 {len(state.operations)} 条 SOP；创建 {state.imported_constraint_count} 个 Blender 近似约束"
    )


def _armature(context):
    return active_session_armature(context)


class GBFR_OT_SopReload(Operator):
    bl_idname = "gbfr.sop_reload"
    bl_label = "重新导入 SOP"
    bl_description = "丢弃未导出编辑并重新读取工作区 SOP"

    def invoke(self, context, event):
        armature = _armature(context)
        if armature is not None and armature.gbfr_sop.dirty:
            return context.window_manager.invoke_confirm(self, event, title="丢弃未导出的 SOP 编辑？")
        return self.execute(context)

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        try:
            populate_sop_state(armature, _active_sop_bundle(context))
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, armature.gbfr_sop.last_status)
        return {"FINISHED"}


class GBFR_OT_SopAdd(Operator):
    bl_idname = "gbfr.sop_add"
    bl_label = "新增 SOP 约束"
    bl_description = "选择已探明的 SOP 类型并添加到当前约束列表"
    bl_options = {"UNDO"}

    constraint_type: EnumProperty(
        name="约束类型", items=NEW_OPERATION_TYPE_ITEMS,
        default="SKIRT_COPY_ROTATION",
    )
    target_ref: StringProperty(name="目标裙骨")
    source_ref: StringProperty(name="来源腿骨")
    axis: EnumProperty(name="Twist 轴", items=AXIS_ITEMS, default="1")
    swing_rate: FloatProperty(
        name="Swing 比例", default=0.5, min=-2.0, max=2.0,
        soft_min=0.0, soft_max=1.0,
    )
    twist_rate: FloatProperty(
        name="Twist 比例", default=0.0, min=-2.0, max=2.0,
        soft_min=0.0, soft_max=1.0,
    )

    def invoke(self, context, _event):
        if _armature(context) is None:
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=440)

    def draw(self, context):
        armature = _armature(context)
        layout = self.layout
        layout.prop(self, "constraint_type")
        if self.constraint_type == "SKIRT_COPY_ROTATION" and armature is not None:
            form = layout.column(align=True)
            form.prop_search(self, "target_ref", armature.data, "bones")
            form.prop_search(self, "source_ref", armature.data, "bones")
            axis = layout.row(align=True)
            axis.label(text="Twist 轴")
            axis.prop(self, "axis", expand=True)
            layout.prop(self, "swing_rate", slider=True)
            layout.prop(self, "twist_rate", slider=True)

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        try:
            if self.constraint_type != "SKIRT_COPY_ROTATION":
                raise ValueError("当前版本不支持该 SOP 约束类型")
            target = _bone_id(armature, self.target_ref)
            source = _bone_id(armature, self.source_ref)
            if target == source:
                raise ValueError("SOP 目标骨和来源骨不能相同")
            operation = make_swing_twist_operation(
                target, source, int(self.axis), self.swing_rate, self.twist_rate,
            )
            operation = _fit_operation_rest_offset(
                armature, operation, self.target_ref, self.source_ref,
            )
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        state = armature.gbfr_sop
        catalog = load_catalog(Path(__file__).parent / "data" / "sop_operations_zh.json")
        state.suspend_updates = True
        item = state.operations.add()
        mapping = _bone_map(armature)
        _populate_item(
            item, operation, catalog.get(operation.type_hash, SopDescription()),
            _blender_preview_status(operation, mapping, _rest_quaternions(armature)), mapping,
        )
        state.active_operation_index = len(state.operations) - 1
        state.suspend_updates = False
        state.dirty = True
        rebuild_sop_preview(armature)
        state.last_status = "已添加复制旋转；当前只在 Blender 内，需显式导出"
        return {"FINISHED"}


class GBFR_OT_SopDelete(Operator):
    bl_idname = "gbfr.sop_delete"
    bl_label = "删除约束"
    bl_description = "删除当前高亮的 SOP 条目；只修改 Blender 内存，需显式导出"
    bl_options = {"UNDO"}

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_sop
        index = state.active_operation_index
        if index < 0 or index >= len(state.operations):
            return {"CANCELLED"}
        state.operations.remove(index)
        state.active_operation_index = min(index, max(0, len(state.operations) - 1))
        state.dirty = True
        rebuild_sop_preview(armature)
        state.last_status = "已删除约束；当前只在 Blender 内，需显式导出"
        return {"FINISHED"}


class GBFR_OT_SopFullCopy(Operator):
    bl_idname = "gbfr.sop_full_copy"
    bl_label = "完整复制 1:1"
    bl_description = "将当前约束的 Swing 和 Twist 比例都设为 1"
    bl_options = {"UNDO"}

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_sop
        index = state.active_operation_index
        if index < 0 or index >= len(state.operations) or not state.operations[index].editable:
            return {"CANCELLED"}
        state.operations[index].swing_rate = 1.0
        state.operations[index].twist_rate = 1.0
        return {"FINISHED"}


class GBFR_OT_SopPreviewRefresh(Operator):
    bl_idname = "gbfr.sop_preview_refresh"
    bl_label = "更新约束预览"
    bl_description = "按当前未导出参数重建 Blender Copy Rotation 近似约束"

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        rebuild_sop_preview(armature)
        armature.gbfr_sop.last_status = (
            f"已更新预览：{armature.gbfr_sop.preview_operation_count} 条操作可执行"
        )
        return {"FINISHED"}


class GBFR_OT_SopSave(Operator):
    bl_idname = "gbfr.sop_save"
    bl_label = "单独导出 SOP 到 unpack"
    bl_description = "保留未知操作与属性，将当前 SOP 编辑原子写入工作区 unpack"

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_sop
        try:
            bundle = _active_sop_bundle(context)
            _sync_workspace_paths(state, bundle)
            target = bundle.sop_edit
            if not _model_export_ready(context, state):
                raise ValueError("请先导出一份当前主体到 unpack，再单独导出 SOP")
            export_sop_to_unpack(armature)
            populate_sop_state(armature, _active_sop_bundle(context))
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        state.last_status = f"已导出 {len(state.operations)} 条 SOP 到 {target.name}"
        self.report({"INFO"}, state.last_status)
        return {"FINISHED"}


class GBFR_OT_SopRestoreSource(Operator):
    bl_idname = "gbfr.sop_restore_source"
    bl_label = "从 source 恢复 SOP"
    bl_description = "只在 Blender 内恢复 source SOP；显式导出前不写入文件"

    def invoke(self, context, _event):
        armature = _armature(context)
        if armature is None or not armature.gbfr_sop.enabled:
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=480)

    def draw(self, _context):
        layout = self.layout
        layout.label(text="将放弃 Blender 中尚未导出的全部 SOP 修改。", icon="ERROR")
        layout.label(text="只恢复到 Blender 内存；unpack 和 build 都不会立即修改。")

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_sop
        try:
            bundle = _active_sop_bundle(context)
            _sync_workspace_paths(state, bundle)
            source = bundle.sop_source
            if source is None:
                raise ValueError("工作区没有登记 source SOP 基线")
            if not source.is_file():
                raise ValueError("工作区没有可用的 source SOP 基线")
            populate_sop_state(
                armature, bundle, load_path_override=source,
            )
        except Exception as error:
            state.last_status = str(error)
            self.report({"ERROR"}, state.last_status)
            return {"CANCELLED"}
        state.dirty = True
        state.last_status = f"已在 Blender 内恢复 {source.name}；需显式导出"
        self.report({"INFO"}, state.last_status)
        return {"FINISHED"}


class GBFR_UL_SopOperations(UIList):
    def filter_items(self, _context, data, propname):
        items = getattr(data, propname)
        query = data.operation_search.strip().casefold()
        mode = data.operation_filter
        flags = []
        for item in items:
            searchable = " ".join((
                item.operation_name, item.target_name, item.source_name,
                item.type_hash, item.discovery_label,
            )).casefold()
            visible = not query or query in searchable
            if mode == "EDITABLE":
                visible = visible and item.editable
            elif mode == "READ_ONLY":
                visible = visible and not item.editable
            flags.append(self.bitflag_filter_item if visible else 0)
        return flags, []

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, index):
        icons = {
            "approximate_constraint": "CONSTRAINT",
            "approximate_unchecked": "CONSTRAINT",
            "rest_guard_failed": "ERROR",
            "not_implemented": "LOCKED",
            "missing_bone": "BONE_DATA",
            "invalid_core_fields": "ERROR",
        }
        icon = icons.get(item.preview_status, "QUESTION")
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            split = layout.split(factor=0.66)
            bones = split.row(align=True)
            number = f"#{item.operation_index:03d}" if item.operation_index >= 0 else "新增"
            bones.label(
                text=f"{number}  {item.target_name} ← {item.source_name}", icon=icon,
            )
            kind = split.row(align=True)
            kind.alignment = "RIGHT"
            kind.label(text=item.operation_name)
        else:
            layout.alignment = "CENTER"
            layout.label(text="", icon=icon)


class GBFR_PT_SopInspector(Panel):
    bl_label = "SOP 约束"
    bl_idname = "VIEW3D_PT_GBFR_Sop_Inspector"
    bl_parent_id = "VIEW3D_PT_GBFR_Workspace"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GBFR"

    @classmethod
    def poll(cls, context):
        armature = _armature(context)
        return armature is not None and hasattr(armature, "gbfr_sop") and armature.gbfr_sop.enabled

    def draw(self, context):
        armature = _armature(context)
        state = armature.gbfr_sop
        layout = self.layout

        if not _model_export_ready(context, state):
            warning = layout.row()
            warning.alert = True
            warning.label(text="请先将当前主体导出到 unpack", icon="ERROR")

        toolbar = layout.row(align=True)
        toolbar.operator("gbfr.sop_save", text="导出 SOP", icon="EXPORT")
        toolbar.operator("gbfr.sop_reload", text="", icon="FILE_REFRESH")
        toolbar.operator("gbfr.sop_restore_source", text="", icon="LOOP_BACK")
        toolbar.separator()
        toolbar.prop(
            state, "preview_constraints", text="预览", toggle=True,
            icon="HIDE_OFF" if state.preview_constraints else "HIDE_ON",
        )
        toolbar.operator("gbfr.sop_preview_refresh", text="", icon="CONSTRAINT")

        summary = layout.grid_flow(
            row_major=True, columns=2, even_columns=True, even_rows=True, align=True,
        )
        summary.label(text=f"{len(state.operations)} 条", icon="LINENUMBERS_ON")
        summary.label(text=f"{state.preview_operation_count} 可用", icon="CHECKMARK")
        summary.label(text=f"{state.unresolved_count} 只读", icon="LOCKED")
        summary.label(text=f"{state.guarded_count} 拦截", icon="ERROR")
        if state.missing_count:
            summary.label(text=f"{state.missing_count} 缺失", icon="BONE_DATA")
        if state.dirty:
            dirty = layout.row()
            dirty.alert = True
            dirty.label(text="Blender 内有尚未导出的 SOP 修改", icon="ERROR")

        layout.prop(state, "operation_search", text="", icon="VIEWZOOM")
        filters = layout.row(align=True)
        filters.prop_enum(state, "operation_filter", "ALL", text="全部")
        filters.prop_enum(state, "operation_filter", "EDITABLE", text="可编辑")
        filters.prop_enum(state, "operation_filter", "READ_ONLY", text="只读")

        header = layout.split(factor=0.66)
        header.label(text="约束骨骼")
        operation_header = header.row()
        operation_header.alignment = "RIGHT"
        operation_header.label(text="操作类型")

        list_row = layout.row()
        list_row.template_list(
            "GBFR_UL_SopOperations", "", state, "operations",
            state, "active_operation_index", rows=10,
        )
        list_actions = list_row.column(align=True)
        list_actions.operator("gbfr.sop_add", text="", icon="ADD")
        remove = list_actions.row(align=True)
        remove.enabled = bool(state.operations)
        remove.operator("gbfr.sop_delete", text="", icon="REMOVE")

        if state.operations and 0 <= state.active_operation_index < len(state.operations):
            item = state.operations[state.active_operation_index]
            box = layout.box()
            title = box.row(align=True)
            number = f"#{item.operation_index:03d}" if item.operation_index >= 0 else "新增"
            title.label(text=f"{number}  {item.operation_name}", icon="CONSTRAINT")
            box.label(
                text=STATUS_LABELS.get(item.preview_status, item.preview_status),
                icon="INFO",
            )
            if item.editable:
                bones = box.column(align=True)
                bones.prop_search(item, "target_ref", armature.data, "bones", text="目标")
                bones.prop_search(item, "source_ref", armature.data, "bones", text="来源")
                axis = box.row(align=True)
                axis.label(text="Twist 轴")
                axis.prop(item, "axis", expand=True)
                box.prop(item, "swing_rate", slider=True)
                box.prop(item, "twist_rate", slider=True)
                actions = box.row(align=True)
                actions.operator("gbfr.sop_full_copy", text="设为 1:1", icon="CON_ROTLIKE")
            else:
                bones = box.row(align=True)
                bones.label(text=f"目标  {item.target_name}", icon="BONE_DATA")
                bones.label(text=f"来源  {item.source_name}", icon="BONE_DATA")
                details = box.row(align=True)
                details.label(text=item.discovery_label or "未探明")
                details.label(text=item.type_hash)

        if state.last_status:
            layout.label(text=state.last_status, icon="INFO")


classes = (
    GBFRSopOperationProperties, GBFRSopStateProperties,
    GBFR_OT_SopReload, GBFR_OT_SopAdd, GBFR_OT_SopDelete,
    GBFR_OT_SopFullCopy, GBFR_OT_SopPreviewRefresh, GBFR_OT_SopSave,
    GBFR_OT_SopRestoreSource,
    GBFR_UL_SopOperations, GBFR_PT_SopInspector,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.gbfr_sop = PointerProperty(type=GBFRSopStateProperties)


def unregister():
    if hasattr(bpy.types.Object, "gbfr_sop"):
        del bpy.types.Object.gbfr_sop
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
