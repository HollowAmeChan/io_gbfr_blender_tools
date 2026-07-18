"""On-demand MOT preview without Actions, animation slots, or NLA tracks."""

from __future__ import annotations

from collections import defaultdict
import math
import uuid

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList
from mathutils import Euler, Matrix, Quaternion, Vector

from .gbfr_animation import AnimationClip, load_mot, read_mot_header
from .gbfr_session import active_session_armature
from .gbfr_workspace import ModelBundle, resolve_model_bundle


_ACTIVE_CLIPS = {}
_APPLYING = False


class GBFRAnimationEntryProperties(PropertyGroup):
    path: StringProperty(name="MOT", subtype="FILE_PATH")
    display_name: StringProperty(name="名称")
    internal_name: StringProperty(name="内部名称")
    frame_count: IntProperty(name="帧数")
    track_count: IntProperty(name="轨道")
    category: StringProperty(name="类别")


def _selection_update(state, context):
    if state.suspend_updates:
        return
    armature = _find_state_owner(state)
    if armature is not None and state.animations:
        try:
            load_selected_animation(armature, context.scene)
        except Exception as error:
            state.last_status = str(error)


class GBFRAnimationStateProperties(PropertyGroup):
    enabled: BoolProperty(default=False)
    minfo_path: StringProperty(name="minfo", subtype="FILE_PATH")
    model_id: StringProperty(name="模型")
    cache_key: StringProperty()
    animations: CollectionProperty(type=GBFRAnimationEntryProperties)
    active_animation_index: IntProperty(default=0, update=_selection_update)
    suspend_updates: BoolProperty(default=False)
    preview_active: BoolProperty(default=False)
    search: StringProperty(name="筛选")
    last_status: StringProperty()


def _find_state_owner(state):
    pointer = state.as_pointer()
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and hasattr(obj, "gbfr_animation") and obj.gbfr_animation.as_pointer() == pointer:
            return obj
    return None


def _bone_map(armature):
    result = {}
    for bone in armature.data.bones:
        value = bone.get("gbfr_bone_id")
        if value is not None and int(value) >= 0:
            result[int(value)] = bone.name
    return result


def _bone_rest_data(armature):
    result = {}
    for bone in armature.data.bones:
        bone_id = bone.get("gbfr_bone_id")
        position = bone.get("gbfr_rest_position")
        rotation = bone.get("gbfr_rest_quaternion")
        scale = bone.get("gbfr_rest_scale")
        if bone_id is None or int(bone_id) < 0 or position is None or rotation is None or scale is None:
            continue
        position = tuple(float(value) for value in position)
        rotation = tuple(float(value) for value in rotation)
        scale = tuple(float(value) for value in scale)
        rest_matrix = Matrix.LocRotScale(Vector(position), Quaternion(rotation), Vector(scale))
        result[int(bone_id)] = {
            "position": position, "rotation": rotation, "scale": scale,
            "rest_inverse": rest_matrix.inverted_safe(),
        }
    return result


def _quaternion_to_euler(rotation):
    w, x, y, z = rotation
    return [
        math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)),
        math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x)))),
        math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)),
    ]


def _make_runtime(armature, clip: AnimationClip):
    mapping = _bone_map(armature)
    rest = _bone_rest_data(armature)
    tracks = defaultdict(list)
    for track in clip.tracks:
        bone_id = 0x900 if track.bone_id == -1 else int(track.bone_id)
        if bone_id in mapping and bone_id in rest and track.property in {0, 1, 2, 3, 4, 5, 7, 8, 9}:
            tracks[bone_id].append(track)
    return {"clip": clip, "mapping": mapping, "rest": rest, "tracks": dict(tracks)}


def _reset_pose(armature):
    identity = Matrix.Identity(4)
    for pose_bone in armature.pose.bones:
        pose_bone.matrix_basis = identity


def _stop_preview(armature, reset=True):
    state = armature.gbfr_animation
    _ACTIVE_CLIPS.pop(state.cache_key, None)
    state.preview_active = False
    if reset:
        _reset_pose(armature)


def _sample_local_matrix(rest, tracks, frame):
    position = list(rest["position"])
    rotation = _quaternion_to_euler(rest["rotation"])
    scale = list(rest["scale"])
    for track in tracks:
        value = track.sample(frame)
        if 0 <= track.property <= 2:
            position[track.property] = value
        elif 3 <= track.property <= 5:
            rotation[track.property - 3] = value
        elif 7 <= track.property <= 9:
            scale[track.property - 7] = value
    return Matrix.LocRotScale(Vector(position), Euler(rotation, "XYZ").to_quaternion(), Vector(scale))


def _apply_runtime(armature, runtime, frame):
    for bone_id, tracks in runtime["tracks"].items():
        rest = runtime["rest"][bone_id]
        animated = _sample_local_matrix(rest, tracks, frame)
        name = runtime["mapping"][bone_id]
        pose_bone = armature.pose.bones.get(name)
        if pose_bone is not None:
            pose_bone.matrix_basis = rest["rest_inverse"] @ animated


@persistent
def _frame_change_handler(scene, _depsgraph=None):
    global _APPLYING
    if _APPLYING:
        return
    _APPLYING = True
    try:
        for armature in (obj for obj in scene.objects if obj.type == "ARMATURE"):
            state = getattr(armature, "gbfr_animation", None)
            if not state or not state.enabled or not state.preview_active:
                continue
            runtime = _ACTIVE_CLIPS.get(state.cache_key)
            if runtime is not None:
                frame = max(0.0, min(float(scene.frame_current_final), runtime["clip"].frame_count - 1.0))
                _apply_runtime(armature, runtime, frame)
    finally:
        _APPLYING = False


@persistent
def _load_post_handler(_unused):
    _ACTIVE_CLIPS.clear()
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and hasattr(obj, "gbfr_animation") and obj.gbfr_animation.preview_active:
            obj.gbfr_animation.preview_active = False
            _reset_pose(obj)


def load_selected_animation(armature, scene):
    state = armature.gbfr_animation
    if not state.animations:
        raise ValueError("当前模型没有 MOT 动画")
    index = min(max(state.active_animation_index, 0), len(state.animations) - 1)
    entry = state.animations[index]
    clip = load_mot(entry.path)
    for other in bpy.data.objects:
        if other != armature and other.type == "ARMATURE" and hasattr(other, "gbfr_animation") and other.gbfr_animation.preview_active:
            _stop_preview(other)
    _reset_pose(armature)
    _ACTIVE_CLIPS[state.cache_key] = _make_runtime(armature, clip)
    state.preview_active = True
    state.last_status = f"正在预览 {entry.display_name}：{clip.frame_count} 帧 / {len(clip.tracks)} 轨道"
    scene.render.fps = 60
    scene.render.fps_base = 1.0
    scene.frame_start = 0
    scene.frame_end = max(0, clip.frame_count - 1)
    scene.frame_set(0)


def populate_animation_state(armature: bpy.types.Object, bundle: ModelBundle) -> None:
    state = armature.gbfr_animation
    _stop_preview(armature)
    state.enabled = False
    state.suspend_updates = True
    state.animations.clear()
    state.minfo_path = str(bundle.minfo)
    state.model_id = bundle.model_id
    if not state.cache_key:
        state.cache_key = uuid.uuid4().hex
    category = "表情" if bundle.model_id.startswith("fp") else "身体"
    errors = []
    for path in bundle.animations:
        try:
            header = read_mot_header(path)
            item = state.animations.add()
            item.name = path.name
            item.path = str(path)
            item.display_name = path.stem
            item.internal_name = header.name
            item.frame_count = header.frame_count
            item.track_count = header.track_count
            item.category = category
        except Exception as error:
            errors.append(f"{path.name}: {error}")
    state.active_animation_index = 0
    state.suspend_updates = False
    state.enabled = bool(state.animations)
    state.last_status = f"已索引 {len(state.animations)} 个{category} MOT；点击列表按需加载"
    if errors:
        state.last_status += f"；跳过 {len(errors)} 个无效文件"


class GBFR_OT_AnimationLoad(Operator):
    bl_idname = "gbfr.animation_load"
    bl_label = "预览选中动画"

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        try:
            load_selected_animation(armature, context.scene)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class GBFR_OT_AnimationPlayPause(Operator):
    bl_idname = "gbfr.animation_play_pause"
    bl_label = "播放/暂停"

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        if not armature.gbfr_animation.preview_active:
            load_selected_animation(armature, context.scene)
        bpy.ops.screen.animation_play()
        return {"FINISHED"}


class GBFR_OT_AnimationFirstFrame(Operator):
    bl_idname = "gbfr.animation_first_frame"
    bl_label = "回到开头"

    def execute(self, context):
        context.scene.frame_set(0)
        return {"FINISHED"}


class GBFR_OT_AnimationStop(Operator):
    bl_idname = "gbfr.animation_stop"
    bl_label = "停止并恢复静止姿态"

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        if context.screen and context.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        _stop_preview(armature)
        armature.gbfr_animation.last_status = "静止姿态；点击动画条目重新预览"
        return {"FINISHED"}


class GBFR_OT_AnimationRefresh(Operator):
    bl_idname = "gbfr.animation_refresh"
    bl_label = "刷新动画列表"

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        try:
            populate_animation_state(armature, resolve_model_bundle(armature.gbfr_animation.minfo_path))
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


def _armature(context):
    return active_session_armature(context)


class GBFR_UL_Animations(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        row = layout.row(align=True)
        row.label(text=item.display_name, icon="ACTION")
        row.label(text=f"{item.frame_count}f")
        row.label(text=f"{item.track_count}轨")

    def filter_items(self, _context, data, property_name):
        values = getattr(data, property_name)
        query = data.search.strip().casefold()
        flags = [self.bitflag_filter_item if not query or query in item.display_name.casefold() or query in item.internal_name.casefold() else 0 for item in values]
        return flags, []


class GBFR_PT_AnimationPreview(Panel):
    bl_label = "MOT 动画"
    bl_idname = "VIEW3D_PT_GBFR_Animation_Preview"
    bl_parent_id = "VIEW3D_PT_GBFR_Workspace"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GBFR"

    @classmethod
    def poll(cls, context):
        armature = _armature(context)
        return armature is not None and hasattr(armature, "gbfr_animation") and armature.gbfr_animation.enabled

    def draw(self, context):
        armature = _armature(context)
        state = armature.gbfr_animation
        layout = self.layout
        row = layout.row(align=True)
        row.prop(state, "search", text="", icon="VIEWZOOM")
        layout.template_list("GBFR_UL_Animations", "", state, "animations", state, "active_animation_index", rows=10)
        controls = layout.row(align=True)
        controls.operator("gbfr.animation_play_pause", text="", icon="PAUSE" if context.screen and context.screen.is_animation_playing else "PLAY")
        controls.operator("gbfr.animation_first_frame", text="", icon="REW")
        controls.operator("gbfr.animation_stop", text="", icon="CANCEL")
        if state.animations:
            item = state.animations[state.active_animation_index]
            details = layout.row(align=True)
            details.label(text=item.internal_name or item.display_name, icon="ACTION")
            details.label(text=f"{item.frame_count}f · {item.track_count}轨")
            if state.preview_active:
                layout.prop(context.scene, "frame_current", text="帧")


classes = (
    GBFRAnimationEntryProperties, GBFRAnimationStateProperties,
    GBFR_OT_AnimationLoad, GBFR_OT_AnimationPlayPause,
    GBFR_OT_AnimationFirstFrame, GBFR_OT_AnimationStop,
    GBFR_OT_AnimationRefresh, GBFR_UL_Animations, GBFR_PT_AnimationPreview,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.gbfr_animation = PointerProperty(type=GBFRAnimationStateProperties)
    if _frame_change_handler not in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.append(_frame_change_handler)
    if _load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post_handler)


def unregister():
    if _frame_change_handler in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(_frame_change_handler)
    if _load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post_handler)
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and hasattr(obj, "gbfr_animation") and obj.gbfr_animation.preview_active:
            _stop_preview(obj)
    _ACTIVE_CLIPS.clear()
    if hasattr(bpy.types.Object, "gbfr_animation"):
        del bpy.types.Object.gbfr_animation
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
