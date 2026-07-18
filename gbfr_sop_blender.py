"""Read-only SOP import and guarded Blender constraint approximation."""

from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList

from .gbfr_sop import (
    SWING_RATE_PROPERTY, SWING_TWIST_OPERATION, TWIST_RATE_PROPERTY,
    TWIST_OPERATION, SopDescription, dominant_axis, guarded_preview_status,
    load_catalog, load_sop,
)
from .gbfr_workspace import ModelBundle, resolve_model_bundle
from .gbfr_session import active_session_armature
from .utils import bone_names_mapping


CONSTRAINT_PREFIX = "GBFR SOP "
STATUS_LABELS = {
    "approximate_constraint": "已创建 Blender 近似约束",
    "rest_guard_failed": "静止姿态自检失败，未执行",
    "not_implemented": "公式未探明，只读导入",
    "missing_bone": "引用骨骼缺失，未执行",
    "invalid_core_fields": "核心字段不完整，未执行",
}


def _bone_map(armature):
    result = {}
    for bone in armature.data.bones:
        value = bone.get("gbfr_bone_id")
        if value is not None and int(value) >= 0:
            result[int(value)] = bone.name
    return result


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


class GBFRSopOperationProperties(PropertyGroup):
    operation_index: IntProperty(name="文件序号", default=-1)
    target_bone: IntProperty(name="Target", default=-1)
    source_bone: IntProperty(name="Source", default=-1)
    target_name: StringProperty(name="Target")
    source_name: StringProperty(name="Source")
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
    source_path: StringProperty(name="SOP 文件", subtype="FILE_PATH")
    minfo_path: StringProperty(name="minfo", subtype="FILE_PATH")
    version: StringProperty(name="版本")
    operations: CollectionProperty(type=GBFRSopOperationProperties)
    active_operation_index: IntProperty(default=0)
    preview_constraints: BoolProperty(
        name="启用核心约束近似预览", default=True, update=_preview_update,
        description="只启用通过静止姿态自检的 Swing/Twist 与 Twist Copy Rotation 近似；不会修改 SOP 文件",
    )
    imported_constraint_count: IntProperty(default=0)
    preview_operation_count: IntProperty(default=0)
    guarded_count: IntProperty(default=0)
    unresolved_count: IntProperty(default=0)
    missing_count: IntProperty(default=0)
    last_status: StringProperty()


def _rest_quaternions(armature):
    result = {}
    for bone in armature.data.bones:
        bone_id = bone.get("gbfr_bone_id")
        value = bone.get("gbfr_rest_quaternion")
        if bone_id is not None and int(bone_id) >= 0 and value is not None and len(value) == 4:
            result[int(bone_id)] = tuple(float(component) for component in value)
    return result


def _display_bone(bone_id, mapping):
    code = f"_{bone_id:03x}"
    friendly = bone_names_mapping.get(code)
    if friendly:
        return f"{friendly[0]} ({code})"
    return mapping.get(bone_id, code)


def _add_copy_rotation(armature, target_name, source_name, operation_index, label, axes, rate):
    target = armature.pose.bones.get(target_name)
    if target is None or source_name not in armature.pose.bones:
        return 0
    constraint = target.constraints.new("COPY_ROTATION")
    constraint.name = f"{CONSTRAINT_PREFIX}#{operation_index:03d} {label} [近似]"
    constraint.target = armature
    constraint.subtarget = source_name
    constraint.target_space = "LOCAL"
    constraint.owner_space = "LOCAL"
    constraint.mix_mode = "BEFORE"
    constraint.show_expanded = False
    constraint.use_x, constraint.use_y, constraint.use_z = axes
    constraint.invert_x = rate < 0.0 and axes[0]
    constraint.invert_y = rate < 0.0 and axes[1]
    constraint.invert_z = rate < 0.0 and axes[2]
    constraint.influence = min(abs(float(rate)), 1.0)
    return 1


def _create_approximate_constraints(armature, operation, mapping):
    axis = dominant_axis(operation)
    target = mapping.get(operation.target_bone)
    source = mapping.get(operation.source_bone)
    if axis is None or target is None or source is None:
        return 0
    twist_rate = operation.floating(TWIST_RATE_PROPERTY)
    if twist_rate is None:
        return 0
    twist_axes = tuple(index == axis for index in range(3))
    count = 0
    if operation.type_hash == SWING_TWIST_OPERATION:
        swing_rate = operation.floating(SWING_RATE_PROPERTY)
        if swing_rate is None:
            return 0
        swing_axes = tuple(index != axis for index in range(3))
        if abs(swing_rate) > 1e-8:
            count += _add_copy_rotation(armature, target, source, operation.index, "Swing", swing_axes, swing_rate)
    if abs(twist_rate) > 1e-8:
        count += _add_copy_rotation(armature, target, source, operation.index, "Twist", twist_axes, twist_rate)
    return count


def populate_sop_state(armature: bpy.types.Object, bundle: ModelBundle) -> None:
    state = armature.gbfr_sop
    state.enabled = False
    state.operations.clear()
    _remove_imported_constraints(armature)
    state.minfo_path = str(bundle.minfo)
    state.source_path = str(bundle.sop or "")
    state.imported_constraint_count = 0
    state.preview_operation_count = 0
    state.guarded_count = 0
    state.unresolved_count = 0
    state.missing_count = 0
    if bundle.sop is None:
        state.last_status = "工作区中没有找到同模型 SOP"
        return

    asset = load_sop(bundle.sop)
    catalog = load_catalog(Path(__file__).parent / "data" / "sop_operations_zh.json")
    mapping = _bone_map(armature)
    rest = _rest_quaternions(armature)
    state.version = f"0x{asset.version:08X}"
    for operation in asset.operations:
        description = catalog.get(operation.type_hash, SopDescription())
        status = guarded_preview_status(operation, rest)
        item = state.operations.add()
        item.name = f"#{operation.index:03d} {description.name}"
        item.operation_index = operation.index
        item.target_bone = operation.target_bone
        item.source_bone = operation.source_bone
        item.target_name = _display_bone(operation.target_bone, mapping)
        item.source_name = _display_bone(operation.source_bone, mapping)
        item.type_hash = f"0x{operation.type_hash:08X}"
        item.operation_name = description.name
        item.category = description.category
        item.discovery = description.discovery
        item.discovery_label = description.discovery_label
        item.runtime_label = description.runtime_label
        item.preview_status = status
        item.purpose = description.purpose
        item.metadata = f"0x{operation.metadata:08X}"
        item.properties_json = json.dumps([
            {
                "hash": f"0x{value.hash:08X}", "type": "float" if value.value_type == 1 else "integer",
                "value": value.value, "raw": f"0x{value.raw_value:08X}",
            }
            for value in operation.properties
        ], ensure_ascii=False)
        if status == "approximate_constraint":
            created = _create_approximate_constraints(armature, operation, mapping)
            state.imported_constraint_count += created
            if not created:
                item.preview_status = "invalid_core_fields"
                state.missing_count += 1
            else:
                state.preview_operation_count += 1
        elif status == "rest_guard_failed":
            state.guarded_count += 1
        elif status == "not_implemented":
            state.unresolved_count += 1
        else:
            state.missing_count += 1
    state.active_operation_index = min(state.active_operation_index, max(0, len(state.operations) - 1))
    state.enabled = True
    _set_constraints_enabled(armature, state.preview_constraints)
    state.last_status = f"读取 {len(state.operations)} 条 SOP；创建 {state.imported_constraint_count} 个 Blender 近似约束"


def _armature(context):
    return active_session_armature(context)


class GBFR_OT_SopReload(Operator):
    bl_idname = "gbfr.sop_reload"
    bl_label = "重新导入 SOP"
    bl_description = "重新读取工作区 SOP；不会导出或修改 SOP"

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        try:
            populate_sop_state(armature, resolve_model_bundle(armature.gbfr_sop.minfo_path))
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, armature.gbfr_sop.last_status)
        return {"FINISHED"}


class GBFR_UL_SopOperations(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        icon = "CONSTRAINT" if item.preview_status == "approximate_constraint" else "ERROR" if item.preview_status == "rest_guard_failed" else "QUESTION"
        row = layout.row(align=True)
        row.label(text=f"#{item.operation_index:03d}", icon=icon)
        row.label(text=item.operation_name)
        row.label(text=item.target_name)


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
        state = _armature(context).gbfr_sop
        layout = self.layout
        row = layout.row(align=True)
        row.prop(state, "preview_constraints", text="近似约束", toggle=True, icon="CONSTRAINT")
        row.label(text=f"{state.preview_operation_count} 可用 · {state.unresolved_count} 未探明 · {state.guarded_count} 拦截")
        if state.missing_count:
            row.label(text=str(state.missing_count), icon="ERROR")
        layout.template_list("GBFR_UL_SopOperations", "", state, "operations", state, "active_operation_index", rows=7)
        if not state.operations:
            return
        item = state.operations[state.active_operation_index]
        details = layout.column(align=True)
        details.label(text=f"{item.target_name} ← {item.source_name}", icon="BONE_DATA")
        details.label(text=STATUS_LABELS.get(item.preview_status, item.preview_status))


classes = (
    GBFRSopOperationProperties, GBFRSopStateProperties,
    GBFR_OT_SopReload, GBFR_UL_SopOperations, GBFR_PT_SopInspector,
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
