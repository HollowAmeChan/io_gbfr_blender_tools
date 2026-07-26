"""Blender properties, editing UI, export, and rest-pose CLP/CLH overlays."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
import subprocess

import bpy
import gpu
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
    FloatVectorProperty, IntProperty, PointerProperty, StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, UIList
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .gbfr_cloth_format import (
    CLP_HEADER_FLOATS, CLP_HEADER_INTS, ClhCollision, ClhDocument,
    ClpDocument, ClpNode, MISSING_BONE, load_clh, load_clp, write_clh, write_clp,
)
from .gbfr_cloth_tools import PRESETS, SelectedBone, delete_nodes, generate_nodes, preset, rebuild_nodes
from .gbfr_model_export_v2 import appended_bone_export_name_map, export_bone_name
from .Entities.ModelSkeleton import ModelSkeleton
from .gbfr_workspace import ModelBundle, resolve_model_bundle, resolve_model_export_targets
from .gbfr_cloth_metadata import CLP_HEADER_GROUPS, CLP_HEADER_UI
from .gbfr_bone_selection import selected_bone_names
from .gbfr_session import active_session_armature
from .utils import bone_names_mapping


_DRAW_HANDLE = None

def _bone_id(bone) -> int | None:
    value = bone.get("gbfr_bone_id")
    if value is not None:
        return int(value)
    if bone.name.startswith("_"):
        try:
            return int(bone.name[1:], 16)
        except ValueError:
            pass
    return None


def _bone_map(armature):
    mapping = {
        bone_id: bone.name
        for bone in armature.data.bones
        if (bone_id := _bone_id(bone)) is not None
    }
    state = getattr(armature, "gbfr_cloth", None)
    if state is not None:
        for group in state.clp_groups:
            for node in group.nodes:
                for raw_attr in ("bone", "up", "down", "side", "poly", "fix"):
                    bone_id = int(getattr(node, raw_attr))
                    bone_name = str(getattr(node, raw_attr + "_ref", "") or "")
                    if bone_name and bone_id not in {-1, MISSING_BONE}:
                        mapping[bone_id] = bone_name
    return mapping


def _bone_display(armature, bone_id: int) -> str:
    if int(bone_id) in {-1, MISSING_BONE}:
        return "无"
    raw_name = f"_{int(bone_id):03x}"
    aliases = bone_names_mapping.get(raw_name)
    if aliases:
        return f"{aliases[0]} ({raw_name})"
    actual_name = _bone_map(armature).get(int(bone_id)) if armature else None
    if actual_name and actual_name != raw_name:
        return f"{actual_name} ({raw_name})"
    return actual_name or raw_name


def _property_armature(owner):
    value = getattr(owner, "id_data", None)
    return value if isinstance(value, bpy.types.Object) and value.type == "ARMATURE" else None


def _bone_reference_update(raw_attr: str, missing_value: int | None = MISSING_BONE):
    reference_attr = raw_attr + "_ref"

    def update(owner, _context):
        if getattr(owner, "suspend_reference_updates", False):
            return
        armature = _property_armature(owner)
        name = getattr(owner, reference_attr, "")
        if not name:
            if missing_value is not None:
                setattr(owner, raw_attr, missing_value)
            _tag_redraw()
            return
        bone = armature.data.bones.get(name) if armature else None
        bone_id = _bone_id(bone) if bone else None
        if bone_id is not None:
            setattr(owner, raw_attr, bone_id)
            if raw_attr in {"p1", "p2"} and armature and hasattr(armature, "gbfr_cloth"):
                for layer in armature.gbfr_cloth.clh_layers:
                    _refresh_collision_references(layer, armature)
        _tag_redraw()

    return update


def _collision_reference_update(owner, _context):
    if owner.suspend_reference_updates:
        return
    if not owner.capsule_ref:
        owner.capsule = -1
        _tag_redraw()
        return
    armature = _property_armature(owner)
    if armature:
        for layer in armature.gbfr_cloth.clh_layers:
            target = layer.collisions.get(owner.capsule_ref)
            if target is not None:
                owner.capsule = target.collision_id
                break
    _tag_redraw()


def _collision_identity_update(owner, _context):
    if owner.suspend_reference_updates:
        return
    armature = _property_armature(owner)
    if armature and hasattr(armature, "gbfr_cloth"):
        for layer in armature.gbfr_cloth.clh_layers:
            _refresh_collision_references(layer, armature)
    _tag_redraw()


def _tag_redraw(_self=None, _context=None):
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _header_attr(xml_name: str) -> str:
    return "header_" + xml_name.rstrip("_")


CLP_HEADER_SECTION_ITEMS = tuple(
    (f"SECTION_{index}", title, "")
    for index, (title, _names) in enumerate(CLP_HEADER_GROUPS)
)

CLP_NODE_SECTION_ITEMS = (
    ("TOPOLOGY", "拓扑", "编辑节点的骨骼连接"),
    ("DYNAMICS", "运动", "编辑摆动、恢复和求解权重"),
    ("COLLISION", "碰撞", "编辑节点碰撞和局部偏移"),
    ("WIND_SCALE", "风力与缩放", "编辑受风和关节缩放"),
    ("RAW", "原始字段", "检查只读原始编码"),
)

CLH_COLLISION_SECTION_ITEMS = (
    ("SHAPE", "形状", "编辑球或胶囊形状"),
    ("ATTACHMENT", "附着", "编辑骨骼附着和局部位置"),
    ("STATE", "状态", "编辑运行状态开关"),
    ("RAW", "原始字段", "检查只读原始编码"),
)

CLP_TOOL_PRESET_ITEMS = tuple(
    (value.key, value.label, f"使用 {value.label} 的 pl1400 参数曲线")
    for value in PRESETS
)


def _clp_tool_preset_update(owner, _context):
    owner.clp_tool_topology = preset(owner.clp_tool_preset).topology


def _clp_create_preset_update(owner, _context):
    owner.topology = preset(owner.preset_key).topology


class GBFRClpNodeProperties(PropertyGroup):
    suspend_reference_updates: BoolProperty(default=False, options={"HIDDEN"})
    data_version: IntProperty(name="数据版本", default=2, description="节点结构版本；通常不需要修改")
    bone: IntProperty(name="节点骨骼原始 ID", default=0, min=0, max=65535)
    bone_ref: StringProperty(name="节点骨骼", description="该拓扑节点附着的骨骼；节点身份不可直接更改")
    up: IntProperty(name="上游原始 ID", default=MISSING_BONE, min=-1, max=65535)
    up_ref: StringProperty(name="上游骨骼", description="同一布料链的上一个骨骼；留空表示无连接", update=_bone_reference_update("up"))
    down: IntProperty(name="下游原始 ID", default=MISSING_BONE, min=-1, max=65535)
    down_ref: StringProperty(name="下游骨骼", description="同一布料链的下一个骨骼；留空表示无连接", update=_bone_reference_update("down"))
    side: IntProperty(name="横向原始 ID", default=MISSING_BONE, min=-1, max=65535)
    side_ref: StringProperty(name="横向骨骼", description="相邻布料链的横向结构连接；留空表示无连接", update=_bone_reference_update("side"))
    poly: IntProperty(name="多边形原始 ID", default=MISSING_BONE, min=-1, max=65535)
    poly_ref: StringProperty(name="多边形骨骼", description="布料面或剪切关系引用；精确公式尚未完全确认", update=_bone_reference_update("poly"))
    fix: IntProperty(name="固定引用原始 ID", default=MISSING_BONE, min=-1, max=65535)
    fix_ref: StringProperty(name="固定目标骨骼", description="该节点使用的固定骨骼引用；留空表示无", update=_bone_reference_update("fix"))
    rotation_limit: FloatProperty(name="摆角限制", subtype="ANGLE", description="节点相对父链的旋转限制，XML 中按弧度保存")
    friction: FloatProperty(name="摩擦", min=0.0, soft_max=1.0, description="节点碰撞摩擦参数")
    gravity_blend_rate: FloatProperty(name="重力混合", soft_min=0.0, soft_max=1.0, description="节点重力混合率；精确公式尚未完全确认")
    offset: FloatVectorProperty(name="局部偏移", size=4, default=(0.0, 0.0, 0.0, 1.0), description="游戏保存的节点 vec4 偏移")
    original_rate: FloatProperty(name="原姿势保持率", soft_min=0.0, soft_max=1.0, description="向原始姿势恢复的节点级比例")
    weight: FloatProperty(name="求解权重", default=1.0, min=0.0, description="求解权重，不应直接理解为公斤质量")
    thickness: FloatProperty(name="碰撞厚度", min=0.0, description="节点参与碰撞时的厚度")
    wind_area: FloatProperty(name="受风面积", description="节点接受风力的有效面积")
    joint_scale: FloatProperty(name="关节缩放", default=1.0, min=0.0, description="节点关节尺度；精确公式尚未完全确认")
    allow_change_scale: BoolProperty(name="允许动态缩放", description="允许运行时修改该节点尺度")
    axis_adjust_rate: FloatProperty(name="轴修正率", default=1.0, description="节点轴向修正比例；精确公式尚未完全确认")
    show_raw_values: BoolProperty(name="显示原始字段", default=False)


class GBFRClpGroupProperties(PropertyGroup):
    xml_path: StringProperty(name="XML 路径", subtype="FILE_PATH")
    output_path: StringProperty(name="Build 路径", subtype="FILE_PATH")
    group_id: IntProperty(name="组 ID", default=-1)
    nodes: CollectionProperty(type=GBFRClpNodeProperties)
    active_node_index: IntProperty(default=0, update=_tag_redraw)
    gravity_vector: FloatVectorProperty(name="重力向量", size=4, default=(0.0, -0.001, 0.0, 1.0), description="该求解组使用的游戏原始 vec4 重力向量")
    show_advanced_header: BoolProperty(name="显示高级与原始字段", default=False)


for _name in CLP_HEADER_FLOATS:
    _label, _description = CLP_HEADER_UI[_name]
    GBFRClpGroupProperties.__annotations__[_header_attr(_name)] = FloatProperty(name=_label, description=_description)
for _name in CLP_HEADER_INTS:
    _label, _description = CLP_HEADER_UI[_name]
    if _name.startswith("b") or _name == "localGravityBlendFlg_":
        GBFRClpGroupProperties.__annotations__[_header_attr(_name)] = BoolProperty(name=_label, description=_description)
    else:
        GBFRClpGroupProperties.__annotations__[_header_attr(_name)] = IntProperty(name=_label, description=_description)


class GBFRClhCollisionProperties(PropertyGroup):
    suspend_reference_updates: BoolProperty(default=False, options={"HIDDEN"})
    data_version: IntProperty(name="数据版本", default=1, description="碰撞记录结构版本")
    collision_id: IntProperty(name="碰撞 ID", min=0, max=65535, description="当前 CLH 层内的端点编号", update=_collision_identity_update)
    p1: IntProperty(name="P1 原始骨骼 ID", min=0, max=65535, update=_tag_redraw)
    p1_ref: StringProperty(name="P1 附着骨骼", description="第一个骨骼空间；位置使用 P1 局部偏移", update=_bone_reference_update("p1", None))
    p2: IntProperty(name="P2 原始骨骼 ID", min=0, max=65535, update=_tag_redraw)
    p2_ref: StringProperty(name="P2 附着骨骼", description="第二个骨骼空间；位置使用 P2 局部偏移", update=_bone_reference_update("p2", None))
    weight: FloatProperty(name="P2 混合权重", soft_min=0.0, soft_max=1.0, update=_tag_redraw, description="在 P1 与 P2 变换后的位置之间插值；不是质量")
    radius: FloatProperty(name="碰撞半径", min=0.0, update=_tag_redraw, description="球端点半径；连接另一端点时共同形成胶囊")
    offset1: FloatVectorProperty(name="P1 局部偏移", size=4, update=_tag_redraw, description="P1 骨骼局部空间中的 vec4 位置")
    offset2: FloatVectorProperty(name="P2 局部偏移", size=4, update=_tag_redraw, description="P2 骨骼局部空间中的 vec4 位置")
    capsule: IntProperty(name="胶囊另一端原始 ID", default=-1, min=-1, max=65535, update=_tag_redraw)
    capsule_ref: StringProperty(name="胶囊另一端", description="引用同层另一碰撞端点；留空时当前记录为球", update=_collision_reference_update)
    disabled_in_battle: BoolProperty(name="战斗状态禁用", description="游戏处于战斗状态时不使用此碰撞")
    disabled_in_idle: BoolProperty(name="待机状态禁用", description="游戏处于待机状态时不使用此碰撞")
    show_raw_values: BoolProperty(name="显示原始字段", default=False)


class GBFRClhLayerProperties(PropertyGroup):
    xml_path: StringProperty(name="XML 路径", subtype="FILE_PATH")
    output_path: StringProperty(name="Build 路径", subtype="FILE_PATH")
    group_id: IntProperty(name="层 ID", default=-1)
    collisions: CollectionProperty(type=GBFRClhCollisionProperties)
    active_collision_index: IntProperty(default=0, update=_tag_redraw)


class GBFRClothStateProperties(PropertyGroup):
    enabled: BoolProperty(default=False)
    workspace_path: StringProperty(name="workspace.json", subtype="FILE_PATH")
    minfo_path: StringProperty(name="minfo", subtype="FILE_PATH")
    character_id: StringProperty(name="角色")
    model_id: StringProperty(name="模型")
    data_tools_path: StringProperty(name="GBFRDataTools", subtype="FILE_PATH")
    clp_groups: CollectionProperty(type=GBFRClpGroupProperties)
    clh_layers: CollectionProperty(type=GBFRClhLayerProperties)
    active_clp_index: IntProperty(default=0, update=_tag_redraw)
    active_clh_index: IntProperty(default=0, update=_tag_redraw)
    show_topology: BoolProperty(name="CLP 骨骼链", default=True, update=_tag_redraw)
    show_collisions: BoolProperty(name="CLH 碰撞", default=True, update=_tag_redraw)
    show_points: BoolProperty(name="端点", default=True, update=_tag_redraw)
    preview_all_clp: BoolProperty(name="显示全部 CLP", default=False, update=_tag_redraw)
    collision_layer_mode: EnumProperty(
        name="CLH 范围", default="CLP_MASK", update=_tag_redraw,
        items=(
            ("CLP_MASK", "当前 CLP 使用层", "按 useCollisionFlags_ 显示"),
            ("ACTIVE", "当前 CLH 层", "只显示当前选择的 CLH"),
            ("ACTIVE_COLLISION", "当前 CLH 碰撞体", "只显示当前 CLH 列表中选择的碰撞体"),
            ("ACTIVE_BONE", "当前骨", "显示所有 CLH 层中涉及当前活动骨骼的碰撞体"),
            ("ALL", "全部 CLH", "显示全部碰撞层"),
        ),
    )
    draw_in_front: BoolProperty(name="始终在前", default=True, update=_tag_redraw)
    clp_edit_mode: EnumProperty(
        name="CLP 编辑内容", default="GROUP",
        items=(("GROUP", "求解组", "编辑组级参数和碰撞层"), ("NODE", "节点", "编辑节点拓扑和局部参数")),
    )
    clp_header_section: EnumProperty(name="参数分类", default="SECTION_0", items=CLP_HEADER_SECTION_ITEMS)
    clp_node_section: EnumProperty(name="节点属性", default="TOPOLOGY", items=CLP_NODE_SECTION_ITEMS)
    clh_collision_section: EnumProperty(name="碰撞属性", default="SHAPE", items=CLH_COLLISION_SECTION_ITEMS)
    clp_tool_preset: EnumProperty(
        name="物理预设", default="SKIRT", items=CLP_TOOL_PRESET_ITEMS,
        update=_clp_tool_preset_update,
    )
    clp_tool_topology: EnumProperty(
        name="连接方式", default="GRID",
        items=(
            ("GRID", "横向网格", "按 root 名排序并连接相同深度"),
            ("CHAINS", "独立骨链", "只生成真实父子纵向连接"),
        ),
    )
    clp_tool_closed: BoolProperty(name="首尾闭合", default=False, description="将排序后的第一串和最后一串横向连接")
    last_status: StringProperty(name="状态")


def _copy_node(target, source: ClpNode, bone_mapping: dict[int, str]) -> None:
    target.suspend_reference_updates = True
    for name in (
        "data_version", "bone", "up", "down", "side", "poly", "fix",
        "rotation_limit", "friction", "gravity_blend_rate", "offset",
        "original_rate", "weight", "thickness", "wind_area", "joint_scale",
        "allow_change_scale", "axis_adjust_rate",
    ):
        setattr(target, name, getattr(source, name))
    _sync_node_references(target, bone_mapping)
    target.suspend_reference_updates = False


def _copy_collision(target, source: ClhCollision, bone_mapping: dict[int, str]) -> None:
    target.suspend_reference_updates = True
    for name in (
        "data_version", "collision_id", "p1", "p2", "weight", "radius",
        "offset1", "offset2", "capsule", "disabled_in_battle", "disabled_in_idle",
    ):
        setattr(target, name, getattr(source, name))
    _sync_collision_bones(target, bone_mapping)
    target.suspend_reference_updates = False


def _sync_node_references(target, bone_mapping: dict[int, str]) -> None:
    for name in ("bone", "up", "down", "side", "poly", "fix"):
        value = int(getattr(target, name))
        setattr(target, name + "_ref", bone_mapping.get(value, "") if value != MISSING_BONE else "")


def _sync_collision_bones(target, bone_mapping: dict[int, str]) -> None:
    target.p1_ref = bone_mapping.get(int(target.p1), "")
    target.p2_ref = bone_mapping.get(int(target.p2), "")


def _refresh_collision_references(layer, armature) -> None:
    by_id = {value.collision_id: value for value in layer.collisions}
    for value in layer.collisions:
        value.name = (
            f"#{value.collision_id} · {_bone_display(armature, value.p1)}"
            f" → {_bone_display(armature, value.p2)}"
        )
    for value in layer.collisions:
        value.suspend_reference_updates = True
        target = by_id.get(value.capsule)
        value.capsule_ref = target.name if target is not None else ""
        value.suspend_reference_updates = False


_EXPORTED_BONE_RE = re.compile(r"^_([0-9a-fA-F]{3})$")


def _export_bone_ids(armature, state) -> dict[str, int]:
    targets = resolve_model_export_targets(state.workspace_path, state.model_id)
    if targets.reference_skeleton is None:
        raise RuntimeError("CLP 创建需要工作区 source skeleton")
    reference = ModelSkeleton.GetRootAs(bytearray(targets.reference_skeleton.read_bytes()), 0)
    mesh_objects = [value for value in armature.children_recursive if value.type == "MESH"]
    appended = appended_bone_export_name_map(armature, mesh_objects, reference)
    result: dict[str, int] = {}
    used: dict[int, str] = {}
    for bone in armature.data.bones:
        final_name = appended.get(bone.name, export_bone_name(bone))
        match = _EXPORTED_BONE_RE.fullmatch(final_name)
        if match is None:
            continue
        bone_id = int(match.group(1), 16)
        previous = used.get(bone_id)
        if previous is not None and previous != bone.name:
            raise RuntimeError(f"导出骨号重复: {previous} / {bone.name} -> {final_name}")
        used[bone_id] = bone.name
        result[bone.name] = bone_id
    return result


def _export_bone_mapping(armature, state) -> tuple[dict[str, int], dict[int, str]]:
    by_name = _export_bone_ids(armature, state)
    return by_name, {bone_id: name for name, bone_id in by_name.items()}


def _selected_bones(context, armature, by_name: dict[str, int], selected_only=True, selected_names=None) -> list[SelectedBone]:
    result = []
    names = (
        list(selected_names) if selected_names is not None
        else selected_bone_names(context, armature) if selected_only
        else [bone.name for bone in armature.data.bones]
    )
    for name in names:
        bone = armature.data.bones.get(name)
        if bone is None:
            if selected_only:
                raise RuntimeError(f"骨骼 {name} 尚未同步到对象数据；请退出编辑模式后重试")
            continue
        bone_id = by_name.get(name)
        if bone_id is None:
            if selected_only:
                raise RuntimeError(f"骨骼 {name} 无法映射为模型导出的 _xxx 编号")
            continue
        result.append(SelectedBone(
            name=name,
            bone_id=bone_id,
            parent_name=bone.parent.name if bone.parent else None,
        ))
    return result


def _replace_group_nodes(group, values, bone_mapping: dict[int, str]) -> None:
    group.nodes.clear()
    for value in values:
        _copy_node(group.nodes.add(), value, bone_mapping)
    group.active_node_index = min(group.active_node_index, max(0, len(group.nodes) - 1))


def _apply_preset_header(group, value) -> None:
    for xml_name, item in value.header.items():
        if xml_name == "gravityVec_":
            group.gravity_vector = item
            continue
        attr = _header_attr(xml_name)
        if hasattr(group, attr):
            setattr(group, attr, item)


def populate_cloth_state(armature: bpy.types.Object, bundle: ModelBundle) -> None:
    state = armature.gbfr_cloth
    state.enabled = False
    state.clp_groups.clear()
    state.clh_layers.clear()
    state.workspace_path = str(bundle.workspace_json)
    state.minfo_path = str(bundle.minfo)
    state.character_id = bundle.character_id
    state.model_id = bundle.model_id
    preference_path = ""
    addon = bpy.context.preferences.addons.get(__package__)
    if addon is not None:
        preference_path = str(getattr(addon.preferences, "gbfr_data_tools_path", "") or "")
    state.data_tools_path = preference_path if Path(preference_path).is_file() else str(bundle.data_tools or "")
    try:
        _by_name, bone_mapping = _export_bone_mapping(armature, state)
    except Exception:
        bone_mapping = _bone_map(armature)
    for record in bundle.cloth_files:
        if record.category == "clp":
            document = load_clp(record.xml)
            group = state.clp_groups.add()
            group.name = record.xml.name.removesuffix(".bxm.xml")
            group.xml_path = str(record.xml)
            group.output_path = str(record.output)
            group.group_id = record.group_id
            for name in CLP_HEADER_FLOATS + CLP_HEADER_INTS:
                setattr(group, _header_attr(name), document.header.get(name, 0))
            group.gravity_vector = document.header.get("gravityVec_", (0.0, -0.001, 0.0, 1.0))
            for value in document.nodes:
                _copy_node(group.nodes.add(), value, bone_mapping)
        elif record.category == "clh":
            document = load_clh(record.xml)
            layer = state.clh_layers.add()
            layer.name = record.xml.name.removesuffix(".bxm.xml")
            layer.xml_path = str(record.xml)
            layer.output_path = str(record.output)
            layer.group_id = record.group_id
            for value in document.collisions:
                _copy_collision(layer.collisions.add(), value, bone_mapping)
            _refresh_collision_references(layer, armature)
    state.active_clp_index = min(state.active_clp_index, max(0, len(state.clp_groups) - 1))
    state.active_clh_index = min(state.active_clh_index, max(0, len(state.clh_layers) - 1))
    state.enabled = True
    state.last_status = f"已载入 {len(state.clp_groups)} 个 CLP / {len(state.clh_layers)} 个 CLH"
    armature["gbfr_workspace"] = str(bundle.workspace_json)
    armature["gbfr_minfo"] = str(bundle.minfo)
    _tag_redraw()


def _armature(context) -> bpy.types.Object | None:
    return active_session_armature(context)


def _node_value(source) -> ClpNode:
    values = {name: getattr(source, name) for name in ClpNode.__dataclass_fields__}
    values["offset"] = tuple(values["offset"])
    return ClpNode(**values)


def _collision_value(source) -> ClhCollision:
    values = {name: getattr(source, name) for name in ClhCollision.__dataclass_fields__}
    values["offset1"] = tuple(values["offset1"])
    values["offset2"] = tuple(values["offset2"])
    return ClhCollision(**values)


def _encode_bxm(xml_path: Path, output_path: Path, tool_path: str) -> None:
    tool = Path(tool_path)
    if not tool.is_file():
        raise RuntimeError("未找到 GBFRDataTools.exe；XML 已保存，但未生成 build BXM")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [str(tool), "xml-to-bxm", "-i", str(xml_path), "-o", str(output_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=flags,
    )
    if result.returncode != 0 or not output_path.is_file():
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"BXM 编码失败: {detail}")


def _save_clp(group, tool_path: str) -> None:
    document = load_clp(group.xml_path)
    for name in CLP_HEADER_FLOATS + CLP_HEADER_INTS:
        document.header[name] = getattr(group, _header_attr(name))
    document.header["gravityVec_"] = tuple(group.gravity_vector)
    document.nodes = [_node_value(value) for value in group.nodes]
    xml_path = write_clp(document)
    _encode_bxm(xml_path, Path(group.output_path), tool_path)


def _save_clh(layer, tool_path: str) -> None:
    document = load_clh(layer.xml_path)
    document.collisions = [_collision_value(value) for value in layer.collisions]
    collision_ids = [value.collision_id for value in document.collisions]
    if len(collision_ids) != len(set(collision_ids)):
        raise ValueError(f"{layer.name} 包含重复 Collision ID")
    xml_path = write_clh(document)
    _encode_bxm(xml_path, Path(layer.output_path), tool_path)


class GBFR_OT_ClothReload(Operator):
    bl_idname = "gbfr.cloth_reload"
    bl_label = "从工作区重新载入"
    bl_description = "丢弃 Blender 中的 cloth 编辑并重新读取 unpack XML"

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        try:
            populate_cloth_state(armature, resolve_model_bundle(armature.gbfr_cloth.minfo_path))
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class GBFR_OT_ClothExport(Operator):
    bl_idname = "gbfr.cloth_export"
    bl_label = "导出 Cloth"
    bl_description = "写回 unpack XML 并编码至 workspace build"
    kind: EnumProperty(items=(("ALL", "全部", ""), ("CLP", "当前 CLP", ""), ("CLH", "当前 CLH", "")), default="ALL")

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_cloth
        try:
            count = 0
            if self.kind in {"ALL", "CLP"}:
                groups = list(state.clp_groups) if self.kind == "ALL" else [state.clp_groups[state.active_clp_index]]
                for group in groups:
                    _save_clp(group, state.data_tools_path)
                    count += 1
            if self.kind in {"ALL", "CLH"}:
                layers = list(state.clh_layers) if self.kind == "ALL" else [state.clh_layers[state.active_clh_index]]
                for layer in layers:
                    _save_clh(layer, state.data_tools_path)
                    count += 1
            state.last_status = f"已写回 unpack 并构建 {count} 个 cloth 文件"
            self.report({"INFO"}, state.last_status)
        except Exception as error:
            state.last_status = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class GBFR_OT_ClpCreateFromSelection(Operator):
    bl_idname = "gbfr.clp_create_from_selection"
    bl_label = "从所选骨链创建 CLP"
    bl_description = "按真实父子层级、root 名顺序和物理预设立即创建可编辑节点"
    bl_options = {"REGISTER", "UNDO"}

    replace_existing: BoolProperty(default=False, options={"SKIP_SAVE"})
    preset_key: EnumProperty(
        name="物理预设", default="SKIRT", items=CLP_TOOL_PRESET_ITEMS,
        update=_clp_create_preset_update,
    )
    topology: EnumProperty(
        name="连接方式", default="GRID",
        items=(
            ("GRID", "横向网格", "按 root 名排序并连接相同深度"),
            ("CHAINS", "独立骨链", "只生成真实父子纵向连接"),
        ),
    )
    closed: BoolProperty(name="首尾闭合", default=False, description="将排序后的第一串和最后一串横向连接")
    apply_header: BoolProperty(
        name="覆盖物理参数",
        default=False,
        description="关闭时保留当前 CLP 的 CLOTH_HEADER；开启时用所选物理预设覆盖。新建节点参数始终来自所选预设",
    )
    selected_bones_json: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, _event):
        armature = _armature(context)
        state = armature.gbfr_cloth if armature else None
        if not state or not state.enabled or not state.clp_groups:
            self.report({"ERROR"}, "请先载入包含 CLP 的模型工作区")
            return {"CANCELLED"}
        names = selected_bone_names(context, armature)
        if not names:
            self.report({"ERROR"}, "请先选择要创建 CLP 的骨骼")
            return {"CANCELLED"}
        self.selected_bones_json = json.dumps(names, ensure_ascii=False)
        self.preset_key = state.clp_tool_preset
        self.topology = state.clp_tool_topology
        self.closed = state.clp_tool_closed
        self.apply_header = False
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        armature = _armature(context)
        state = armature.gbfr_cloth if armature else None
        group_id = state.clp_groups[state.active_clp_index].group_id if state and state.clp_groups else -1
        action = "替换" if self.replace_existing else "添加"
        layout.label(text=f"{action}到 CLP {group_id}", icon='CONSTRAINT_BONE')
        if self.replace_existing:
            layout.label(text="将清空当前组的全部节点", icon='ERROR')
        layout.prop(self, "preset_key")
        layout.prop(self, "topology", expand=True)
        if self.topology == "GRID":
            layout.prop(self, "closed", toggle=True, icon='LOOP_FORWARDS')
        layout.prop(self, "apply_header", toggle=True, icon='PRESET')

    def execute(self, context):
        armature = _armature(context)
        state = armature.gbfr_cloth if armature else None
        if not state or not state.enabled or not state.clp_groups:
            self.report({"ERROR"}, "请先载入包含 CLP 的模型工作区")
            return {"CANCELLED"}
        group = state.clp_groups[state.active_clp_index]
        try:
            by_name, bone_mapping = _export_bone_mapping(armature, state)
            snapshot = json.loads(self.selected_bones_json) if self.selected_bones_json else None
            selected = _selected_bones(context, armature, by_name, selected_names=snapshot)
            generated, selected_preset, chains = generate_nodes(
                selected,
                self.preset_key,
                self.topology,
                self.closed,
            )
            selected_ids = {bone.bone_id for bone in selected}
            for node in generated:
                for field in ("up", "down", "side", "poly", "fix"):
                    target = getattr(node, field)
                    if target != MISSING_BONE and target not in selected_ids:
                        raise RuntimeError(
                            f"生成连接越过本次骨骼选择: {node.bone}.{field} -> {target}"
                        )
            state.clp_tool_preset = self.preset_key
            state.clp_tool_topology = self.topology
            state.clp_tool_closed = self.closed
            current = [] if self.replace_existing else [_node_value(value) for value in group.nodes]
            current_ids = {value.bone for value in current}
            duplicates = [value.bone for value in generated if value.bone in current_ids]
            if duplicates:
                names = ", ".join(bone_mapping.get(value, f"_{value:03x}") for value in duplicates[:8])
                raise ValueError(f"当前 CLP 已包含所选节点: {names}")
            generated_ids = {value.bone for value in generated}
            cleared_activated = 0
            for value in current:
                for field in ("up", "down", "side", "poly"):
                    if getattr(value, field) in generated_ids:
                        setattr(value, field, MISSING_BONE)
                        cleared_activated += 1
            _replace_group_nodes(group, current + generated, bone_mapping)
            if self.apply_header:
                _apply_preset_header(group, selected_preset)
            group.active_node_index = len(current)
            action = "替换" if self.replace_existing else "添加"
            detail = f"，清除 {cleared_activated} 个被新骨号激活的旧悬空引用" if cleared_activated else ""
            state.last_status = f"已{action} {len(generated)} 个节点 / {len(chains)} 串{detail}，尚未写入 XML"
            self.report({"INFO"}, state.last_status)
            _tag_redraw()
            return {"FINISHED"}
        except Exception as error:
            state.last_status = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class GBFR_OT_ClpDeleteSelection(Operator):
    bl_idname = "gbfr.clp_delete_selection"
    bl_label = "精准删除所选 CLP 节点"
    bl_description = "删除当前 CLP 中与所选骨骼对应的节点，并清除所有悬空引用"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        armature = _armature(context)
        state = armature.gbfr_cloth if armature else None
        if not state or not state.enabled or not state.clp_groups:
            return {"CANCELLED"}
        group = state.clp_groups[state.active_clp_index]
        try:
            by_name, bone_mapping = _export_bone_mapping(armature, state)
            selected_names = set(selected_bone_names(context, armature))
            if not selected_names:
                raise ValueError("请先选择要从当前 CLP 删除的骨骼")
            remove_ids = {by_name[name] for name in selected_names if name in by_name}
            values, removed_count, cleared_count = delete_nodes(
                [_node_value(value) for value in group.nodes], remove_ids,
            )
            if removed_count == 0:
                raise ValueError("当前 CLP 中没有与所选骨骼对应的节点")
            _replace_group_nodes(group, values, bone_mapping)
            state.last_status = f"已删除 {removed_count} 个节点并清除 {cleared_count} 个引用，尚未写入 XML"
            self.report({"INFO"}, state.last_status)
            _tag_redraw()
            return {"FINISHED"}
        except Exception as error:
            state.last_status = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class GBFR_OT_ClpRebuildConnections(Operator):
    bl_idname = "gbfr.clp_rebuild_connections"
    bl_label = "重建当前 CLP 连接"
    bl_description = "保留节点物理参数，只按父子层级、root 名顺序和闭合设置重建连接"
    bl_options = {"REGISTER", "UNDO"}

    topology: EnumProperty(
        name="连接方式", default="GRID",
        items=(
            ("GRID", "横向网格", "按 root 名排序并连接相同深度"),
            ("CHAINS", "独立骨链", "只生成真实父子纵向连接"),
        ),
    )
    closed: BoolProperty(name="首尾闭合", default=False, description="将排序后的第一串和最后一串横向连接")

    def invoke(self, context, _event):
        armature = _armature(context)
        state = armature.gbfr_cloth if armature else None
        if not state or not state.enabled or not state.clp_groups:
            return {"CANCELLED"}
        self.topology = state.clp_tool_topology
        self.closed = state.clp_tool_closed
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "topology", expand=True)
        if self.topology == "GRID":
            layout.prop(self, "closed", toggle=True, icon='LOOP_FORWARDS')

    def execute(self, context):
        armature = _armature(context)
        state = armature.gbfr_cloth if armature else None
        if not state or not state.enabled or not state.clp_groups:
            return {"CANCELLED"}
        group = state.clp_groups[state.active_clp_index]
        if not group.nodes:
            self.report({"WARNING"}, "当前 CLP 没有节点")
            return {"CANCELLED"}
        try:
            by_name, bone_mapping = _export_bone_mapping(armature, state)
            bones = _selected_bones(context, armature, by_name, selected_only=False)
            mapped_ids = {bone.bone_id for bone in bones}
            missing = [value.bone for value in group.nodes if value.bone not in mapped_ids]
            if missing:
                names = ", ".join(f"_{value:03x}" for value in missing[:8])
                raise ValueError(f"当前骨架无法解析这些 CLP 节点: {names}")
            values = rebuild_nodes(
                [_node_value(value) for value in group.nodes],
                bones,
                self.topology,
                self.closed,
            )
            _replace_group_nodes(group, values, bone_mapping)
            state.clp_tool_topology = self.topology
            state.clp_tool_closed = self.closed
            state.last_status = f"已重建 {len(values)} 个节点的连接，物理参数保持不变"
            self.report({"INFO"}, state.last_status)
            _tag_redraw()
            return {"FINISHED"}
        except Exception as error:
            state.last_status = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class GBFR_OT_SelectBoneReference(Operator):
    bl_idname = "gbfr.select_bone_reference"
    bl_label = "选中引用骨骼"
    bl_description = "在当前骨架中选中此引用指向的骨骼"
    bl_options = {"UNDO"}

    bone_name: StringProperty()

    def execute(self, context):
        armature = _armature(context)
        bone = armature.data.bones.get(self.bone_name) if armature else None
        if bone is None:
            self.report({"WARNING"}, "引用骨骼不存在；请重新载入工作区")
            return {"CANCELLED"}
        bpy.context.view_layer.objects.active = armature
        armature.select_set(True)
        for item in armature.data.bones:
            item.select = False
        bone.hide = False
        bone.select = True
        armature.data.bones.active = bone
        return {"FINISHED"}


class GBFR_OT_ToggleCollisionLayer(Operator):
    bl_idname = "gbfr.toggle_collision_layer"
    bl_label = "切换碰撞层"
    bl_description = "切换当前 CLP 求解组使用的 CLH 碰撞层"
    bl_options = {"UNDO"}

    layer_id: IntProperty(min=0, max=30)

    def execute(self, context):
        armature = _armature(context)
        state = armature.gbfr_cloth if armature else None
        if not state or not state.clp_groups:
            return {"CANCELLED"}
        group = state.clp_groups[state.active_clp_index]
        attr = _header_attr("useCollisionFlags_")
        setattr(group, attr, int(getattr(group, attr)) ^ (1 << self.layer_id))
        _tag_redraw()
        return {"FINISHED"}


class GBFR_OT_ClhAddCollision(Operator):
    bl_idname = "gbfr.clh_add_collision"
    bl_label = "添加碰撞端点"
    bl_options = {"UNDO"}

    def execute(self, context):
        armature = _armature(context)
        state = armature.gbfr_cloth if armature else None
        if not state or not state.clh_layers:
            return {"CANCELLED"}
        layer = state.clh_layers[state.active_clh_index]
        value = layer.collisions.add()
        value.collision_id = max((item.collision_id for item in list(layer.collisions)[:-1]), default=-1) + 1
        _refresh_collision_references(layer, armature)
        layer.active_collision_index = len(layer.collisions) - 1
        _tag_redraw()
        return {"FINISHED"}


class GBFR_OT_ClhRemoveCollision(Operator):
    bl_idname = "gbfr.clh_remove_collision"
    bl_label = "删除碰撞端点"
    bl_options = {"UNDO"}

    def execute(self, context):
        armature = _armature(context)
        state = armature.gbfr_cloth if armature else None
        if not state or not state.clh_layers:
            return {"CANCELLED"}
        layer = state.clh_layers[state.active_clh_index]
        if not layer.collisions:
            return {"CANCELLED"}
        layer.collisions.remove(layer.active_collision_index)
        _refresh_collision_references(layer, armature)
        layer.active_collision_index = min(layer.active_collision_index, max(0, len(layer.collisions) - 1))
        _tag_redraw()
        return {"FINISHED"}


def _draw_bone_reference(layout, owner, raw_attr: str, armature, label: str, editable=True) -> None:
    reference_attr = raw_attr + "_ref"
    row = layout.row(align=True)
    field = row.row(align=True)
    field.enabled = editable
    field.prop_search(owner, reference_attr, armature.data, "bones", text=label, icon="BONE_DATA")
    name = getattr(owner, reference_attr)
    if name:
        operator = row.operator("gbfr.select_bone_reference", text="", icon="RESTRICT_SELECT_OFF")
        operator.bone_name = name
    else:
        raw_value = int(getattr(owner, raw_attr))
        if raw_value not in {-1, MISSING_BONE}:
            warning = row.row(align=True)
            warning.alert = True
            warning.label(text=f"未解析 _{raw_value:03x}", icon="ERROR")


class GBFR_UL_ClpGroups(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        mask = int(getattr(item, _header_attr("useCollisionFlags_")))
        layers = ",".join(str(index) for index in range(31) if mask & (1 << index)) or "无"
        layout.label(text=f"CLP {item.group_id} · {len(item.nodes)} 节点 · CLH {layers}", icon="CONSTRAINT_BONE")


class GBFR_UL_ClpNodes(UIList):
    def draw_item(self, context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        armature = _armature(context)
        node_name = item.bone_ref or _bone_display(armature, item.bone)
        down_name = item.down_ref or _bone_display(armature, item.down)
        layout.label(
            text=(
                f"{node_name}  ·  "
                f"下游 {down_name}"
            ),
            icon="BONE_DATA",
        )


class GBFR_UL_ClhLayers(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=f"CLH {item.group_id} · {len(item.collisions)} 碰撞体", icon="MESH_UVSPHERE")


class GBFR_UL_ClhCollisions(UIList):
    def draw_item(self, context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        armature = _armature(context)
        shape = "球" if item.capsule < 0 else f"胶囊 → #{item.capsule}"
        layout.label(
            text=f"#{item.collision_id}  {shape} · {_bone_display(armature, item.p1)}",
            icon="MESH_UVSPHERE" if item.capsule < 0 else "META_CAPSULE",
        )


class GBFR_PT_ClothEditor(Panel):
    bl_label = "Cloth 预览"
    bl_idname = "VIEW3D_PT_GBFR_Cloth_Editor"
    bl_parent_id = "VIEW3D_PT_GBFR_Workspace"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GBFR"

    @classmethod
    def poll(cls, context):
        armature = _armature(context)
        return armature is not None and hasattr(armature, "gbfr_cloth") and armature.gbfr_cloth.enabled

    def draw(self, context):
        armature = _armature(context)
        state = armature.gbfr_cloth
        layout = self.layout
        summary = layout.row(align=True)
        summary.label(text=f"{len(state.clp_groups)} CLP", icon="CONSTRAINT_BONE")
        summary.label(text=f"{len(state.clh_layers)} CLH", icon="MESH_UVSPHERE")
        layout.label(text="视口显示")
        row = layout.row(align=True)
        row.prop(state, "show_topology", text="骨骼链", toggle=True, icon="CONSTRAINT_BONE")
        row.prop(state, "show_collisions", text="碰撞体", toggle=True, icon="MESH_UVSPHERE")
        row.prop(state, "show_points", text="端点", toggle=True, icon="PIVOT_CURSOR")
        view = layout.row(align=True)
        view.prop(state, "preview_all_clp", text="全部 CLP")
        view.prop(state, "draw_in_front", text="置前")
        layout.prop(state, "collision_layer_mode", text="碰撞范围")
        if state.collision_layer_mode == "ACTIVE_BONE":
            bone = armature.data.bones.active
            bone_id = _bone_id(bone) if bone else None
            if bone_id is None:
                layout.label(text="请先在骨架上选择一个骨骼", icon="INFO")
            else:
                layout.label(text=f"过滤骨骼: {_bone_display(armature, bone_id)}", icon="BONE_DATA")


def _draw_clp_group_editor(layout, armature, state, group):
    collision_layers = layout.box()
    collision_layers.label(text="使用的 CLH 碰撞层", icon="MESH_UVSPHERE")
    mask = int(getattr(group, _header_attr("useCollisionFlags_")))
    layer_grid = collision_layers.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
    for layer in state.clh_layers:
        if not 0 <= layer.group_id < 31:
            continue
        operator = layer_grid.operator(
            "gbfr.toggle_collision_layer",
            text=f"CLH {layer.group_id} ({len(layer.collisions)})",
            icon="CHECKBOX_HLT" if mask & (1 << layer.group_id) else "CHECKBOX_DEHLT",
            depress=bool(mask & (1 << layer.group_id)),
        )
        operator.layer_id = layer.group_id

    parameters = layout.box()
    parameters.label(text="求解参数", icon="PHYSICS")
    parameters.prop(group, "gravity_vector")
    parameters.prop(state, "clp_header_section", text="分类")
    section_index = int(state.clp_header_section.removeprefix("SECTION_"))
    _title, names = CLP_HEADER_GROUPS[section_index]
    values = parameters.column(align=True)
    for name in names:
        values.prop(group, _header_attr(name))

    layout.prop(group, "show_advanced_header", text="原始 Header", toggle=True, icon="SETTINGS")
    if group.show_advanced_header:
        raw_values = layout.column(align=True)
        raw_values.enabled = False
        for name in ("dataVersion_", "id_", "useCollisionFlags_"):
            raw_values.prop(group, _header_attr(name))


def _draw_clp_node_editor(layout, armature, state, group):
    layout.template_list("GBFR_UL_ClpNodes", "", group, "nodes", group, "active_node_index", rows=6)
    if not group.nodes:
        return
    node = group.nodes[group.active_node_index]
    summary = layout.row(align=True)
    summary.label(text=f"节点 {node.bone_ref or _bone_display(armature, node.bone)}", icon="BONE_DATA")
    layout.prop(state, "clp_node_section", text="编辑")

    if state.clp_node_section == "TOPOLOGY":
        _draw_bone_reference(layout, node, "bone", armature, "节点骨骼", editable=False)
        for name, label in (("up", "上游骨骼"), ("down", "下游骨骼"), ("side", "横向骨骼"), ("poly", "多边形骨骼"), ("fix", "固定目标骨骼")):
            _draw_bone_reference(layout, node, name, armature, label)
    elif state.clp_node_section == "DYNAMICS":
        for name in ("rotation_limit", "gravity_blend_rate", "original_rate", "weight"):
            layout.prop(node, name)
    elif state.clp_node_section == "COLLISION":
        for name in ("friction", "thickness", "offset"):
            layout.prop(node, name)
    elif state.clp_node_section == "WIND_SCALE":
        for name in ("wind_area", "joint_scale", "allow_change_scale", "axis_adjust_rate"):
            layout.prop(node, name)
    else:
        raw_values = layout.column(align=True)
        raw_values.enabled = False
        raw_values.prop(node, "data_version")
        for name in ("bone", "up", "down", "side", "poly", "fix"):
            raw_values.prop(node, name)


class GBFR_PT_ClpEditor(Panel):
    bl_label = "CLP 求解"
    bl_idname = "VIEW3D_PT_GBFR_Clp_Editor"
    bl_parent_id = "VIEW3D_PT_GBFR_Workspace"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GBFR"

    @classmethod
    def poll(cls, context):
        return GBFR_PT_ClothEditor.poll(context)

    def draw(self, context):
        armature = _armature(context)
        state = armature.gbfr_cloth
        layout = self.layout
        layout.template_list("GBFR_UL_ClpGroups", "", state, "clp_groups", state, "active_clp_index", rows=3)
        if not state.clp_groups:
            layout.label(text="当前工作区没有 CLP", icon="INFO")
            return
        group = state.clp_groups[state.active_clp_index]
        toolbar = layout.row(align=True)
        toolbar.label(text=f"CLP {group.group_id} · {len(group.nodes)} 节点")
        op = toolbar.operator("gbfr.cloth_export", text="写入当前", icon="EXPORT")
        op.kind = "CLP"
        layout.prop(state, "clp_edit_mode", expand=True)
        if state.clp_edit_mode == "GROUP":
            _draw_clp_group_editor(layout, armature, state, group)
        else:
            _draw_clp_node_editor(layout, armature, state, group)


class GBFR_PT_ClhEditor(Panel):
    bl_label = "CLH 碰撞"
    bl_idname = "VIEW3D_PT_GBFR_Clh_Editor"
    bl_parent_id = "VIEW3D_PT_GBFR_Workspace"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GBFR"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return GBFR_PT_ClothEditor.poll(context)

    def draw(self, context):
        armature = _armature(context)
        state = armature.gbfr_cloth
        layout = self.layout
        layout.template_list("GBFR_UL_ClhLayers", "", state, "clh_layers", state, "active_clh_index", rows=3)
        if not state.clh_layers:
            layout.label(text="当前工作区没有 CLH", icon="INFO")
            return
        layer = state.clh_layers[state.active_clh_index]
        toolbar = layout.row(align=True)
        toolbar.label(text=f"CLH {layer.group_id} · {len(layer.collisions)} 碰撞体")
        op = toolbar.operator("gbfr.cloth_export", text="写入当前", icon="EXPORT")
        op.kind = "CLH"
        list_row = layout.row()
        list_row.template_list("GBFR_UL_ClhCollisions", "", layer, "collisions", layer, "active_collision_index", rows=6)
        tools = list_row.column(align=True)
        tools.operator("gbfr.clh_add_collision", text="", icon="ADD")
        tools.operator("gbfr.clh_remove_collision", text="", icon="REMOVE")
        if not layer.collisions:
            return
        value = layer.collisions[layer.active_collision_index]
        summary = layout.row(align=True)
        shape = "球" if value.capsule < 0 else f"胶囊 → #{value.capsule}"
        summary.label(text=f"#{value.collision_id} · {shape}", icon="MESH_UVSPHERE" if value.capsule < 0 else "META_CAPSULE")
        layout.prop(state, "clh_collision_section", text="编辑")
        if state.clh_collision_section == "SHAPE":
            layout.prop(value, "radius")
            layout.prop_search(value, "capsule_ref", layer, "collisions", text="胶囊另一端", icon="META_CAPSULE")
        elif state.clh_collision_section == "ATTACHMENT":
            _draw_bone_reference(layout, value, "p1", armature, "P1 附着骨骼")
            layout.prop(value, "offset1")
            _draw_bone_reference(layout, value, "p2", armature, "P2 附着骨骼")
            layout.prop(value, "offset2")
            layout.prop(value, "weight")
        elif state.clh_collision_section == "STATE":
            layout.prop(value, "disabled_in_battle")
            layout.prop(value, "disabled_in_idle")
        else:
            raw_values = layout.column(align=True)
            raw_values.enabled = False
            for name in ("data_version", "collision_id", "p1", "p2", "capsule"):
                raw_values.prop(value, name)


def _bone_point(armature, mapping, bone_id, offset=(0.0, 0.0, 0.0, 0.0)):
    name = mapping.get(int(bone_id))
    pose_bone = armature.pose.bones.get(name) if name else None
    if pose_bone is None:
        return None
    return armature.matrix_world @ (pose_bone.matrix @ Vector(offset[:3]))


def _append_line(lines, first, second):
    if first is not None and second is not None:
        lines.extend((tuple(first), tuple(second)))


def _append_cross(lines, center, size):
    if center is None:
        return
    for axis in (Vector((size, 0, 0)), Vector((0, size, 0)), Vector((0, 0, size))):
        _append_line(lines, center - axis, center + axis)


def _append_sphere(lines, center, radius, segments=16):
    if center is None or radius <= 0:
        return
    for plane in range(3):
        for index in range(segments):
            a = math.tau * index / segments
            b = math.tau * (index + 1) / segments
            first = Vector(center)
            second = Vector(center)
            coordinates = ((math.cos(a), math.sin(a)), (math.cos(b), math.sin(b)))
            axes = ((0, 1), (0, 2), (1, 2))[plane]
            first[axes[0]] += coordinates[0][0] * radius
            first[axes[1]] += coordinates[0][1] * radius
            second[axes[0]] += coordinates[1][0] * radius
            second[axes[1]] += coordinates[1][1] * radius
            _append_line(lines, first, second)


def _append_capsule(lines, first, radius_first, second, radius_second, segments=12):
    axis = Vector(second) - Vector(first)
    if axis.length < 1e-8:
        return
    axis.normalize()
    reference = Vector((0, 1, 0)) if abs(axis.y) < 0.8 else Vector((1, 0, 0))
    tangent = axis.cross(reference).normalized()
    bitangent = axis.cross(tangent).normalized()
    for index in range(segments):
        angle = math.tau * index / segments
        radial = tangent * math.cos(angle) + bitangent * math.sin(angle)
        _append_line(lines, Vector(first) + radial * radius_first, Vector(second) + radial * radius_second)


def _visible_clp(state):
    if state.preview_all_clp:
        return list(state.clp_groups)
    return [state.clp_groups[state.active_clp_index]] if state.clp_groups else []


def _visible_clh(state, clp_groups):
    if state.collision_layer_mode == "ALL":
        return list(state.clh_layers)
    if state.collision_layer_mode in {"ACTIVE", "ACTIVE_COLLISION"}:
        return [state.clh_layers[state.active_clh_index]] if state.clh_layers else []
    if state.collision_layer_mode == "ACTIVE_BONE":
        return list(state.clh_layers)
    mask = 0
    for group in clp_groups:
        mask |= int(getattr(group, _header_attr("useCollisionFlags_")))
    return [layer for layer in state.clh_layers if 0 <= layer.group_id < 31 and mask & (1 << layer.group_id)]


def _collision_draw_ids(state, layer, active_bone_id=None):
    values = {value.collision_id: value for value in layer.collisions}
    if state.collision_layer_mode == "ACTIVE_COLLISION":
        if not layer.collisions:
            return set(), set()
        index = min(max(0, layer.active_collision_index), len(layer.collisions) - 1)
        shape_ids = {layer.collisions[index].collision_id}
    elif state.collision_layer_mode == "ACTIVE_BONE":
        if active_bone_id is None:
            return set(), set()
        direct_ids = {
            value.collision_id
            for value in layer.collisions
            if active_bone_id in {value.p1, value.p2}
        }
        shape_ids = set(direct_ids)
        shape_ids.update(
            value.collision_id
            for value in layer.collisions
            if value.capsule in direct_ids
        )
    else:
        shape_ids = set(values)

    point_ids = set(shape_ids)
    point_ids.update(
        values[collision_id].capsule
        for collision_id in shape_ids
        if collision_id in values and values[collision_id].capsule in values
    )
    return point_ids, shape_ids


def _draw_armature(armature, batches):
    state = armature.gbfr_cloth
    mapping = _bone_map(armature)
    groups = _visible_clp(state)
    if state.show_topology:
        longitudinal, lateral, fixed, points = [], [], [], []
        for group in groups:
            positions = {node.bone: _bone_point(armature, mapping, node.bone) for node in group.nodes}
            for node in group.nodes:
                origin = positions.get(node.bone)
                _append_line(longitudinal, origin, positions.get(node.down))
                _append_line(lateral, origin, positions.get(node.side))
                if node.poly != node.side:
                    _append_line(lateral, origin, positions.get(node.poly))
                _append_line(fixed, origin, positions.get(node.fix))
                if state.show_points:
                    _append_cross(points, origin, 0.006)
        batches.extend(((longitudinal, (0.25, 0.95, 0.45, 0.95), 2.0), (lateral, (0.95, 0.35, 0.85, 0.95), 2.0), (fixed, (1.0, 0.55, 0.15, 0.95), 2.4), (points, (1.0, 0.9, 0.25, 0.95), 1.2)))
    if state.show_collisions:
        collision_lines, points = [], []
        active_bone = armature.data.bones.active
        active_bone_id = _bone_id(active_bone) if active_bone else None
        for layer in _visible_clh(state, groups):
            endpoints = {}
            for value in layer.collisions:
                first = _bone_point(armature, mapping, value.p1, value.offset1)
                second = _bone_point(armature, mapping, value.p2, value.offset2)
                if first is None or second is None:
                    continue
                center = first.lerp(second, value.weight)
                endpoints[value.collision_id] = (center, value.radius)
            point_ids, shape_ids = _collision_draw_ids(state, layer, active_bone_id)
            for collision_id in point_ids:
                endpoint = endpoints.get(collision_id)
                if endpoint is None:
                    continue
                center, radius = endpoint
                _append_sphere(collision_lines, center, radius)
                if state.show_points:
                    _append_cross(points, center, max(radius * 0.2, 0.003))
            for value in layer.collisions:
                if value.collision_id not in shape_ids:
                    continue
                current = endpoints.get(value.collision_id)
                linked = endpoints.get(value.capsule)
                if current and linked:
                    _append_capsule(collision_lines, linked[0], linked[1], current[0], current[1])
        batches.extend(((collision_lines, (0.15, 0.9, 1.0, 0.82), 1.5), (points, (0.95, 1.0, 1.0, 0.95), 1.0)))


def _draw_overlay():
    context = bpy.context
    batches = []
    armature = active_session_armature(context)
    if armature is None or armature not in context.visible_objects:
        return
    state = getattr(armature, "gbfr_cloth", None)
    if not state or not state.enabled:
        return
    draw_in_front = state.draw_in_front
    _draw_armature(armature, batches)
    batches = [batch for batch in batches if batch[0]]
    if not batches:
        return
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE" if draw_in_front else "LESS_EQUAL")
    gpu.state.depth_mask_set(False)
    try:
        for lines, color, width in batches:
            shader.bind()
            shader.uniform_float("color", color)
            gpu.state.line_width_set(width)
            batch_for_shader(shader, "LINES", {"pos": lines}).draw(shader)
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("NONE")


classes = (
    GBFRClpNodeProperties, GBFRClpGroupProperties, GBFRClhCollisionProperties,
    GBFRClhLayerProperties, GBFRClothStateProperties, GBFR_OT_ClothReload,
    GBFR_OT_ClothExport, GBFR_OT_ClpCreateFromSelection,
    GBFR_OT_ClpDeleteSelection, GBFR_OT_ClpRebuildConnections,
    GBFR_OT_SelectBoneReference,
    GBFR_OT_ToggleCollisionLayer, GBFR_OT_ClhAddCollision, GBFR_OT_ClhRemoveCollision,
    GBFR_UL_ClpGroups, GBFR_UL_ClpNodes, GBFR_UL_ClhLayers,
    GBFR_UL_ClhCollisions, GBFR_PT_ClothEditor, GBFR_PT_ClpEditor, GBFR_PT_ClhEditor,
)


def register():
    global _DRAW_HANDLE
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.gbfr_cloth = PointerProperty(type=GBFRClothStateProperties)
    _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(_draw_overlay, (), "WINDOW", "POST_VIEW")


def unregister():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        _DRAW_HANDLE = None
    if hasattr(bpy.types.Object, "gbfr_cloth"):
        del bpy.types.Object.gbfr_cloth
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
