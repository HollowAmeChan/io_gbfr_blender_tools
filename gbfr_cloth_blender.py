"""Blender properties, editing UI, export, and rest-pose CLP/CLH overlays."""

from __future__ import annotations

import math
from pathlib import Path
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
    ClpDocument, ClpNode, load_clh, load_clp, write_clh, write_clp,
)
from .gbfr_workspace import ModelBundle, WorkspaceError, resolve_model_bundle


_DRAW_HANDLE = None


def _tag_redraw(_self=None, _context=None):
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _header_attr(xml_name: str) -> str:
    return "header_" + xml_name.rstrip("_")


class GBFRClpNodeProperties(PropertyGroup):
    data_version: IntProperty(name="dataVersion", default=2)
    bone: IntProperty(name="骨骼 ID", default=0, min=0, max=65535)
    up: IntProperty(name="上游", default=4095, min=-1, max=65535)
    down: IntProperty(name="下游", default=4095, min=-1, max=65535)
    side: IntProperty(name="横向", default=4095, min=-1, max=65535)
    poly: IntProperty(name="多边形", default=4095, min=-1, max=65535)
    fix: IntProperty(name="固定引用", default=4095, min=-1, max=65535)
    rotation_limit: FloatProperty(name="旋转限制", subtype="ANGLE")
    friction: FloatProperty(name="摩擦", min=0.0, soft_max=1.0)
    gravity_blend_rate: FloatProperty(name="重力混合", soft_min=0.0, soft_max=1.0)
    offset: FloatVectorProperty(name="偏移", size=4, default=(0.0, 0.0, 0.0, 1.0))
    original_rate: FloatProperty(name="原姿势率", soft_min=0.0, soft_max=1.0)
    weight: FloatProperty(name="权重", default=1.0, min=0.0)
    thickness: FloatProperty(name="厚度", min=0.0)
    wind_area: FloatProperty(name="受风面积")
    joint_scale: FloatProperty(name="关节缩放", default=1.0, min=0.0)
    allow_change_scale: BoolProperty(name="允许缩放")
    axis_adjust_rate: FloatProperty(name="轴调整率", default=1.0)


class GBFRClpGroupProperties(PropertyGroup):
    xml_path: StringProperty(name="XML 路径", subtype="FILE_PATH")
    output_path: StringProperty(name="Build 路径", subtype="FILE_PATH")
    group_id: IntProperty(name="组 ID", default=-1)
    nodes: CollectionProperty(type=GBFRClpNodeProperties)
    active_node_index: IntProperty(default=0, update=_tag_redraw)
    gravity_vector: FloatVectorProperty(name="gravityVec_", size=4, default=(0.0, -0.001, 0.0, 1.0))


for _name in CLP_HEADER_FLOATS:
    GBFRClpGroupProperties.__annotations__[_header_attr(_name)] = FloatProperty(name=_name)
for _name in CLP_HEADER_INTS:
    if _name.startswith("b"):
        GBFRClpGroupProperties.__annotations__[_header_attr(_name)] = BoolProperty(name=_name)
    else:
        GBFRClpGroupProperties.__annotations__[_header_attr(_name)] = IntProperty(name=_name)


class GBFRClhCollisionProperties(PropertyGroup):
    data_version: IntProperty(name="dataVersion", default=1)
    collision_id: IntProperty(name="ID", min=0, max=65535)
    p1: IntProperty(name="骨骼 P1", min=0, max=65535, update=_tag_redraw)
    p2: IntProperty(name="骨骼 P2", min=0, max=65535, update=_tag_redraw)
    weight: FloatProperty(name="骨骼混合权重", soft_min=0.0, soft_max=1.0, update=_tag_redraw)
    radius: FloatProperty(name="半径", min=0.0, update=_tag_redraw)
    offset1: FloatVectorProperty(name="P1 局部偏移", size=4, update=_tag_redraw)
    offset2: FloatVectorProperty(name="P2 局部偏移", size=4, update=_tag_redraw)
    capsule: IntProperty(name="胶囊连接 ID", default=-1, min=-1, max=65535, update=_tag_redraw)
    disabled_in_battle: BoolProperty(name="战斗中禁用")
    disabled_in_idle: BoolProperty(name="待机中禁用")


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
            ("ALL", "全部 CLH", "显示全部碰撞层"),
        ),
    )
    draw_in_front: BoolProperty(name="始终在前", default=True, update=_tag_redraw)
    last_status: StringProperty(name="状态")


def _copy_node(target, source: ClpNode) -> None:
    for name in (
        "data_version", "bone", "up", "down", "side", "poly", "fix",
        "rotation_limit", "friction", "gravity_blend_rate", "offset",
        "original_rate", "weight", "thickness", "wind_area", "joint_scale",
        "allow_change_scale", "axis_adjust_rate",
    ):
        setattr(target, name, getattr(source, name))


def _copy_collision(target, source: ClhCollision) -> None:
    for name in (
        "data_version", "collision_id", "p1", "p2", "weight", "radius",
        "offset1", "offset2", "capsule", "disabled_in_battle", "disabled_in_idle",
    ):
        setattr(target, name, getattr(source, name))


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
                _copy_node(group.nodes.add(), value)
        elif record.category == "clh":
            document = load_clh(record.xml)
            layer = state.clh_layers.add()
            layer.name = record.xml.name.removesuffix(".bxm.xml")
            layer.xml_path = str(record.xml)
            layer.output_path = str(record.output)
            layer.group_id = record.group_id
            for value in document.collisions:
                _copy_collision(layer.collisions.add(), value)
    state.active_clp_index = min(state.active_clp_index, max(0, len(state.clp_groups) - 1))
    state.active_clh_index = min(state.active_clh_index, max(0, len(state.clh_layers) - 1))
    state.enabled = True
    state.last_status = f"已载入 {len(state.clp_groups)} 个 CLP / {len(state.clh_layers)} 个 CLH"
    armature["gbfr_workspace"] = str(bundle.workspace_json)
    armature["gbfr_minfo"] = str(bundle.minfo)
    _tag_redraw()


def _armature(context) -> bpy.types.Object | None:
    obj = context.object
    if obj is None:
        return None
    if obj.type == "ARMATURE":
        return obj
    if obj.type == "MESH":
        return obj.find_armature()
    return None


def _node_value(source) -> ClpNode:
    return ClpNode(**{name: getattr(source, name) for name in ClpNode.__dataclass_fields__})


def _collision_value(source) -> ClhCollision:
    return ClhCollision(**{name: getattr(source, name) for name in ClhCollision.__dataclass_fields__})


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
        layer.active_collision_index = min(layer.active_collision_index, max(0, len(layer.collisions) - 1))
        _tag_redraw()
        return {"FINISHED"}


class GBFR_UL_ClpGroups(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=f"{item.group_id}: {item.name}", icon="CONSTRAINT_BONE")


class GBFR_UL_ClpNodes(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=f"_{item.bone:03x}  up:{item.up} down:{item.down}", icon="BONE_DATA")


class GBFR_UL_ClhLayers(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=f"{item.group_id}: {item.name}", icon="MESH_UVSPHERE")


class GBFR_UL_ClhCollisions(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        shape = "球" if item.capsule < 0 else f"胶囊 <- {item.capsule}"
        layout.label(text=f"{item.collision_id}: _{item.p1:03x}/_{item.p2:03x} {shape}")


class GBFR_PT_ClothEditor(Panel):
    bl_label = "Cloth 数据"
    bl_idname = "VIEW3D_PT_GBFR_Cloth_Editor"
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
        layout.label(text=f"{state.character_id} / {state.model_id}", icon="ARMATURE_DATA")
        row = layout.row(align=True)
        row.operator("gbfr.cloth_reload", icon="FILE_REFRESH")
        op = row.operator("gbfr.cloth_export", text="全部写入 build", icon="EXPORT")
        op.kind = "ALL"
        if state.last_status:
            layout.label(text=state.last_status, icon="INFO")

        box = layout.box()
        box.label(text="视图调试（静态数据）", icon="HIDE_OFF")
        row = box.row(align=True)
        row.prop(state, "show_topology", toggle=True)
        row.prop(state, "show_collisions", toggle=True)
        row.prop(state, "show_points", toggle=True)
        box.prop(state, "preview_all_clp")
        box.prop(state, "collision_layer_mode")
        box.prop(state, "draw_in_front")

        layout.separator()
        layout.label(text="CLP 求解组")
        layout.template_list("GBFR_UL_ClpGroups", "", state, "clp_groups", state, "active_clp_index", rows=3)
        if state.clp_groups:
            group = state.clp_groups[state.active_clp_index]
            row = layout.row()
            op = row.operator("gbfr.cloth_export", text="写入当前 CLP", icon="EXPORT")
            op.kind = "CLP"
            header = layout.box()
            header.label(text="Header")
            header.prop(group, "gravity_vector")
            grid = header.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
            for name in CLP_HEADER_FLOATS + CLP_HEADER_INTS:
                grid.prop(group, _header_attr(name), text=name)
            layout.template_list("GBFR_UL_ClpNodes", "", group, "nodes", group, "active_node_index", rows=4)
            if group.nodes:
                node = group.nodes[group.active_node_index]
                node_box = layout.box()
                node_box.label(text=f"骨骼 _{node.bone:03x} ({node.bone})")
                for name in ("up", "down", "side", "poly", "fix"):
                    node_box.prop(node, name)
                for name in ("rotation_limit", "friction", "gravity_blend_rate", "offset", "original_rate", "weight", "thickness", "wind_area", "joint_scale", "allow_change_scale", "axis_adjust_rate"):
                    node_box.prop(node, name)

        layout.separator()
        layout.label(text="CLH 碰撞层")
        layout.template_list("GBFR_UL_ClhLayers", "", state, "clh_layers", state, "active_clh_index", rows=3)
        if state.clh_layers:
            layer = state.clh_layers[state.active_clh_index]
            row = layout.row(align=True)
            op = row.operator("gbfr.cloth_export", text="写入当前 CLH", icon="EXPORT")
            op.kind = "CLH"
            row.operator("gbfr.clh_add_collision", text="", icon="ADD")
            row.operator("gbfr.clh_remove_collision", text="", icon="REMOVE")
            layout.template_list("GBFR_UL_ClhCollisions", "", layer, "collisions", layer, "active_collision_index", rows=5)
            if layer.collisions:
                value = layer.collisions[layer.active_collision_index]
                collision = layout.box()
                collision.label(text=f"Collision ID {value.collision_id}")
                for name in ("p1", "p2", "weight", "radius", "offset1", "offset2", "capsule", "disabled_in_battle", "disabled_in_idle"):
                    collision.prop(value, name)


def _bone_map(armature):
    result = {}
    for bone in armature.data.bones:
        value = bone.get("gbfr_bone_id")
        if value is None and bone.name.startswith("_"):
            try:
                value = int(bone.name[1:], 16)
            except ValueError:
                continue
        if value is not None:
            result[int(value)] = bone.name
    return result


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
    if state.collision_layer_mode == "ACTIVE":
        return [state.clh_layers[state.active_clh_index]] if state.clh_layers else []
    mask = 0
    for group in clp_groups:
        mask |= int(getattr(group, _header_attr("useCollisionFlags_")))
    return [layer for layer in state.clh_layers if 0 <= layer.group_id < 31 and mask & (1 << layer.group_id)]


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
        for layer in _visible_clh(state, groups):
            endpoints = {}
            values = {value.collision_id: value for value in layer.collisions}
            for value in layer.collisions:
                first = _bone_point(armature, mapping, value.p1, value.offset1)
                second = _bone_point(armature, mapping, value.p2, value.offset2)
                if first is None or second is None:
                    continue
                center = first.lerp(second, value.weight)
                endpoints[value.collision_id] = (center, value.radius)
                _append_sphere(collision_lines, center, value.radius)
                if state.show_points:
                    _append_cross(points, center, max(value.radius * 0.2, 0.003))
            for value in layer.collisions:
                current = endpoints.get(value.collision_id)
                linked = endpoints.get(value.capsule)
                if current and linked:
                    _append_capsule(collision_lines, linked[0], linked[1], current[0], current[1])
        batches.extend(((collision_lines, (0.15, 0.9, 1.0, 0.82), 1.5), (points, (0.95, 1.0, 1.0, 0.95), 1.0)))


def _draw_overlay():
    context = bpy.context
    batches = []
    draw_in_front = False
    for armature in (obj for obj in context.visible_objects if obj.type == "ARMATURE"):
        state = getattr(armature, "gbfr_cloth", None)
        if state and state.enabled:
            draw_in_front = draw_in_front or state.draw_in_front
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
    GBFR_OT_ClothExport, GBFR_OT_ClhAddCollision, GBFR_OT_ClhRemoveCollision,
    GBFR_UL_ClpGroups, GBFR_UL_ClpNodes, GBFR_UL_ClhLayers,
    GBFR_UL_ClhCollisions, GBFR_PT_ClothEditor,
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
