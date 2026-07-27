"""MOT source preview, editable Actions, NLA edit layers, and unpack export."""

from __future__ import annotations

from collections import defaultdict
import math
from pathlib import Path
import uuid

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList
from mathutils import Euler, Matrix, Quaternion, Vector

from .gbfr_animation import (
    AnimationClip, guess_mot_annotation, load_mot, read_mot_header,
    write_mot_template_atomic,
)
from .gbfr_session import active_session_armature
from .gbfr_workspace import ModelBundle, resolve_model_bundle


_ACTIVE_CLIPS = {}
_APPLYING = False
_ACTION_ROLE = "gbfr_mot_role"
_ACTION_SESSION = "gbfr_mot_session"
_ACTION_FILENAME = "gbfr_mot_filename"
_ROLE_BASE = "BASE"
_ROLE_EDIT = "EDIT"
_MANAGED_NLA_PREFIX = "[GBFR MOT]"


class GBFRAnimationEntryProperties(PropertyGroup):
    path: StringProperty(name="MOT", subtype="FILE_PATH")
    source_path: StringProperty(name="源 MOT", subtype="FILE_PATH")
    template_path: StringProperty(name="Action 模板 MOT", subtype="FILE_PATH")
    unpack_path: StringProperty(name="unpack MOT", subtype="FILE_PATH")
    display_name: StringProperty(name="名称")
    internal_name: StringProperty(name="内部名称")
    guessed_annotation: StringProperty(name="推测注释")
    frame_count: IntProperty(name="帧数")
    track_count: IntProperty(name="轨道")
    category: StringProperty(name="类别")
    action_name: StringProperty(name="Base Action")
    edit_action_name: StringProperty(name="Edit Action")
    passthrough_track_count: IntProperty(name="原样保留轨道")
    export_exists: BoolProperty(name="已有 unpack MOT")
    validation_status: StringProperty(name="验证状态")


def _selection_update(state, context):
    if state.suspend_updates:
        return
    armature = _find_state_owner(state)
    if armature is not None and state.animations and not _has_imported_actions(state):
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
    export_preview_active: BoolProperty(default=False)
    export_preview_entry_name: StringProperty()
    active_action_name: StringProperty(name="当前 Action")
    search: StringProperty(name="筛选")
    last_status: StringProperty()


def _find_state_owner(state):
    pointer = state.as_pointer()
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and hasattr(obj, "gbfr_animation") and obj.gbfr_animation.as_pointer() == pointer:
            return obj
    return None


def _entry_action(entry):
    return bpy.data.actions.get(entry.action_name) if entry.action_name else None


def _entry_edit_action(entry):
    return bpy.data.actions.get(entry.edit_action_name) if entry.edit_action_name else None


def _has_imported_actions(state) -> bool:
    return any(_entry_action(entry) is not None for entry in state.animations)


def _active_entry(state):
    if not state.animations:
        return None
    index = min(max(0, state.active_animation_index), len(state.animations) - 1)
    return state.animations[index]


def _find_saved_action(state, filename: str, role: str):
    for action in bpy.data.actions:
        if (
            action.get(_ACTION_SESSION) == state.cache_key
            and action.get(_ACTION_FILENAME) == filename
            and action.get(_ACTION_ROLE) == role
        ):
            return action
    return None


def _tag_action(action, state, entry, role: str) -> None:
    action[_ACTION_SESSION] = state.cache_key
    action[_ACTION_FILENAME] = entry.name
    action[_ACTION_ROLE] = role
    action["gbfr_mot_source_path"] = entry.source_path
    action["gbfr_mot_template_path"] = _entry_template_path(entry)
    action["gbfr_mot_unpack_path"] = entry.unpack_path
    action["gbfr_mot_model_id"] = state.model_id
    action["gbfr_mot_frame_count"] = int(entry.frame_count)


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
            "rest_matrix": rest_matrix,
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
    state.export_preview_active = False
    state.export_preview_entry_name = ""
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
            if (
                not state or not state.enabled or not state.preview_active
                or (_has_imported_actions(state) and not state.export_preview_active)
            ):
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
            obj.gbfr_animation.export_preview_active = False
            obj.gbfr_animation.export_preview_entry_name = ""
            _reset_pose(obj)


def load_selected_animation(armature, scene):
    state = armature.gbfr_animation
    if not state.animations:
        raise ValueError("当前模型没有 MOT 动画")
    if _has_imported_actions(state):
        raise ValueError("当前会话已有可编辑 Action；源 MOT 直接预览已禁用")
    index = min(max(state.active_animation_index, 0), len(state.animations) - 1)
    entry = state.animations[index]
    clip = load_mot(_entry_source_preview_path(entry))
    _start_runtime_preview(armature, scene, clip)
    state.last_status = (
        f"正在预览 {entry.display_name}：{clip.frame_count} 帧 / {len(clip.tracks)} 轨道"
    )


def _start_runtime_preview(
    armature, scene, clip: AnimationClip, *, exported_entry_name: str = "",
) -> None:
    for other in bpy.data.objects:
        if (
            other != armature and other.type == "ARMATURE"
            and hasattr(other, "gbfr_animation")
            and other.gbfr_animation.preview_active
        ):
            _stop_preview(other)
    _stop_preview(armature)
    state = armature.gbfr_animation
    _ACTIVE_CLIPS[state.cache_key] = _make_runtime(armature, clip)
    state.preview_active = True
    state.export_preview_active = bool(exported_entry_name)
    state.export_preview_entry_name = exported_entry_name
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
    for asset in bundle.animations:
        try:
            header = read_mot_header(asset.preview)
            item = state.animations.add()
            item.name = asset.name
            item.path = str(asset.preview)
            item.source_path = str(asset.source or "")
            item.unpack_path = str(asset.unpack)
            item.display_name = asset.preview.stem
            item.internal_name = header.name
            item.guessed_annotation = guess_mot_annotation(asset.name)
            item.frame_count = header.frame_count
            item.track_count = header.track_count
            item.category = category
            item.export_exists = asset.unpack.is_file()
            base = _find_saved_action(state, item.name, _ROLE_BASE)
            edit = _find_saved_action(state, item.name, _ROLE_EDIT)
            item.action_name = base.name if base is not None else ""
            item.edit_action_name = edit.name if edit is not None else ""
            if base is not None:
                item.template_path = str(
                    base.get("gbfr_mot_template_path")
                    or base.get("gbfr_mot_imported_from_unpack")
                    or ""
                )
            item.passthrough_track_count = (
                int(base.get("gbfr_mot_passthrough_tracks", 0))
                if base is not None else 0
            )
        except Exception as error:
            errors.append(f"{asset.name}: {error}")
    state.active_animation_index = 0
    state.suspend_updates = False
    state.enabled = bool(state.animations)
    imported = sum(_entry_action(entry) is not None for entry in state.animations)
    if state.active_action_name and bpy.data.actions.get(state.active_action_name) is None:
        state.active_action_name = ""
    state.last_status = f"已索引 {len(state.animations)} 个{category} MOT"
    if imported:
        state.last_status += f"；保留 {imported} 个可编辑 Action，源 MOT 直接预览已禁用"
    else:
        state.last_status += "；点击列表按需预览"
    if errors:
        state.last_status += f"；跳过 {len(errors)} 个无效文件"


def _clear_managed_nla(animation_data) -> None:
    if animation_data is None:
        return
    for track in list(animation_data.nla_tracks):
        if track.name.startswith(_MANAGED_NLA_PREFIX):
            animation_data.nla_tracks.remove(track)


def _detach_action_stack(armature) -> None:
    animation_data = armature.animation_data
    if animation_data is None:
        return
    animation_data.action = None
    _clear_managed_nla(animation_data)
    animation_data.action_blend_type = "REPLACE"
    animation_data.action_influence = 1.0


def _bind_entry_action(armature, entry, scene) -> None:
    base = _entry_action(entry)
    if base is None:
        raise ValueError(f"{entry.display_name} 尚未导入 Action")
    _stop_preview(armature)
    animation_data = armature.animation_data_create()
    animation_data.action = None
    _clear_managed_nla(animation_data)
    edit = _entry_edit_action(entry)
    if edit is None:
        animation_data.action = base
        animation_data.action_blend_type = "REPLACE"
    else:
        track = animation_data.nla_tracks.new()
        track.name = f"{_MANAGED_NLA_PREFIX} Base"
        strip = track.strips.new(base.name, 0, base)
        strip.name = f"{_MANAGED_NLA_PREFIX} Base"
        strip.blend_type = "REPLACE"
        strip.extrapolation = "NOTHING"
        animation_data.action = edit
        animation_data.action_blend_type = "COMBINE"
        animation_data.action_influence = 1.0
    state = armature.gbfr_animation
    state.active_action_name = base.name
    scene.render.fps = 60
    scene.render.fps_base = 1.0
    scene.frame_start = 0
    scene.frame_end = max(0, int(entry.frame_count) - 1)
    scene.frame_set(min(max(scene.frame_current, scene.frame_start), scene.frame_end))


def _action_entry(state, action_name: str):
    for entry in state.animations:
        action = _entry_action(entry)
        if action is not None and action.name == action_name:
            return entry
    return None


def _curve_values_are_constant(values, epsilon=1e-10) -> bool:
    first = values[0]
    return all(abs(value - first) <= epsilon for value in values[1:])


def _add_action_curve(action, data_path: str, index: int, values, group: str) -> None:
    curve = action.fcurves.new(data_path, index=index, action_group=group)
    if _curve_values_are_constant(values):
        frames_and_values = ((0.0, float(values[0])),)
    else:
        frames_and_values = tuple((float(frame), float(value)) for frame, value in enumerate(values))
    curve.keyframe_points.add(len(frames_and_values))
    curve.keyframe_points.foreach_set(
        "co", [component for pair in frames_and_values for component in pair],
    )
    for point in curve.keyframe_points:
        point.interpolation = "LINEAR"
    curve.update()


def _create_action_from_basis_samples(
    armature, state, entry, samples_by_bone, role: str, name_suffix: str,
):
    action = bpy.data.actions.new(
        name=f"GBFR MOT | {state.model_id} | {entry.display_name} | {name_suffix}"
    )
    _tag_action(action, state, entry, role)
    action.use_frame_range = True
    action.frame_start = 0
    action.frame_end = max(0, int(entry.frame_count) - 1)
    try:
        for bone_name, samples in samples_by_bone.items():
            pose_bone = armature.pose.bones.get(bone_name)
            if pose_bone is None:
                raise ValueError(f"Action 烘焙时找不到骨骼 {bone_name}")
            pose_bone.rotation_mode = "QUATERNION"
            locations, rotations, scales = samples
            for index in range(3):
                _add_action_curve(
                    action, pose_bone.path_from_id("location"), index,
                    [value[index] for value in locations], bone_name,
                )
            for index in range(4):
                _add_action_curve(
                    action, pose_bone.path_from_id("rotation_quaternion"), index,
                    [value[index] for value in rotations], bone_name,
                )
            for index in range(3):
                _add_action_curve(
                    action, pose_bone.path_from_id("scale"), index,
                    [value[index] for value in scales], bone_name,
                )
        return action
    except Exception:
        bpy.data.actions.remove(action)
        raise


def _clip_basis_samples(armature, clip: AnimationClip):
    runtime = _make_runtime(armature, clip)
    supported = {0, 1, 2, 3, 4, 5, 7, 8, 9}
    seen = set()
    problems = []
    passthrough = []
    for track in clip.tracks:
        bone_id = 0x900 if track.bone_id == -1 else int(track.bone_id)
        identity = (bone_id, int(track.property))
        if track.property not in supported:
            passthrough.append((track.bone_id, track.property, "不支持的属性"))
            continue
        if bone_id not in runtime["mapping"] or bone_id not in runtime["rest"]:
            passthrough.append((track.bone_id, track.property, "当前骨架没有此骨"))
            continue
        if identity in seen:
            problems.append(f"重复骨 {track.bone_id} 属性 {track.property}")
        seen.add(identity)
    if problems:
        raise ValueError("MOT 无法转为 Action: " + "；".join(problems[:8]))

    result = {}
    for bone_id, tracks in runtime["tracks"].items():
        rest = runtime["rest"][bone_id]
        locations = []
        rotations = []
        scales = []
        previous = None
        for frame in range(clip.frame_count):
            basis = rest["rest_inverse"] @ _sample_local_matrix(rest, tracks, frame)
            location, rotation, scale = basis.decompose()
            rotation.normalize()
            if previous is not None:
                rotation.make_compatible(previous)
            previous = rotation.copy()
            locations.append(tuple(location))
            rotations.append(tuple(rotation))
            scales.append(tuple(scale))
        result[runtime["mapping"][bone_id]] = (locations, rotations, scales)
    return result, tuple(passthrough)


def _validate_bound_action(armature, entry, clip, scene):
    runtime = _make_runtime(armature, clip)
    maximum = 0.0
    worst = None
    decomposition_maximum = 0.0
    decomposition_worst = None
    original_frame = scene.frame_current
    try:
        for frame in range(clip.frame_count):
            scene.frame_set(frame)
            for bone_id, tracks in runtime["tracks"].items():
                pose_bone = armature.pose.bones[runtime["mapping"][bone_id]]
                expected = runtime["rest"][bone_id]["rest_inverse"] @ _sample_local_matrix(
                    runtime["rest"][bone_id], tracks, frame,
                )
                actual = pose_bone.matrix_basis
                location, rotation, scale = expected.decompose()
                projected = Matrix.LocRotScale(location, rotation, scale)
                for row in range(4):
                    for column in range(4):
                        error = abs(actual[row][column] - projected[row][column])
                        if error > maximum:
                            maximum = error
                            worst = (frame, runtime["mapping"][bone_id], row, column)
                        decomposition_error = abs(
                            projected[row][column] - expected[row][column]
                        )
                        if decomposition_error > decomposition_maximum:
                            decomposition_maximum = decomposition_error
                            decomposition_worst = (
                                frame, runtime["mapping"][bone_id], row, column,
                            )
        if maximum > 1e-4:
            frame, bone_name, row, column = worst
            detail = f"帧 {frame}，骨骼 {bone_name}，矩阵 [{row},{column}]"
            if decomposition_worst is not None:
                d_frame, d_bone, d_row, d_column = decomposition_worst
                detail += (
                    f"；TRS 分解误差 {decomposition_maximum:.6g} 位于帧 {d_frame}、"
                    f"骨骼 {d_bone}、矩阵 [{d_row},{d_column}]"
                )
            raise ValueError(f"Action 与 MOT 的 TRS 投影不一致 {maximum:.6g}（{detail}）")
        entry.validation_status = (
            f"Action 一致 {maximum:.2g}；源矩阵 TRS 投影 {decomposition_maximum:.2g}"
        )
        return maximum, decomposition_maximum
    finally:
        scene.frame_set(min(max(original_frame, scene.frame_start), scene.frame_end))


def _sample_bound_action_for_template(armature, clip: AnimationClip, scene):
    runtime = _make_runtime(armature, clip)
    mapping = runtime["mapping"]
    rest = runtime["rest"]
    supported = {0, 1, 2, 3, 4, 5, 7, 8, 9}
    normalized_tracks = []
    seen = set()
    for track in clip.tracks:
        bone_id = 0x900 if track.bone_id == -1 else int(track.bone_id)
        identity = (bone_id, int(track.property))
        editable = (
            track.property in supported
            and bone_id in mapping
            and bone_id in rest
        )
        if editable and identity in seen:
            raise ValueError(f"MOT 存在重复轨道 _{bone_id:03x}.{track.property}")
        if editable:
            seen.add(identity)
        normalized_tracks.append((bone_id, int(track.property), editable))

    sampled = [
        [] if editable else [track.sample(frame) for frame in range(clip.frame_count)]
        for track, (_bone_id, _prop, editable) in zip(clip.tracks, normalized_tracks)
    ]
    previous_eulers = {}
    original_frame = scene.frame_current
    try:
        for frame in range(clip.frame_count):
            scene.frame_set(frame)
            values_by_bone = {}
            for bone_id in {
                bone_id for bone_id, _property, editable in normalized_tracks if editable
            }:
                pose_bone = armature.pose.bones[mapping[bone_id]]
                exact_basis = rest[bone_id]["rest_inverse"] @ _sample_local_matrix(
                    rest[bone_id], runtime["tracks"][bone_id], frame,
                )
                location, rotation, scale = exact_basis.decompose()
                projected_basis = Matrix.LocRotScale(location, rotation, scale)
                edit_delta = projected_basis.inverted_safe() @ pose_bone.matrix_basis
                local = rest[bone_id]["rest_matrix"] @ exact_basis @ edit_delta
                location, rotation, scale = local.decompose()
                rotation.normalize()
                previous = previous_eulers.get(bone_id)
                euler = (
                    rotation.to_euler("XYZ", previous)
                    if previous is not None
                    else rotation.to_euler("XYZ")
                )
                previous_eulers[bone_id] = euler.copy()
                values_by_bone[bone_id] = (tuple(location), tuple(euler), tuple(scale))
            for index, (bone_id, prop, editable) in enumerate(normalized_tracks):
                if not editable:
                    continue
                location, rotation, scale = values_by_bone[bone_id]
                if prop <= 2:
                    value = location[prop]
                elif prop <= 5:
                    value = rotation[prop - 3]
                else:
                    value = scale[prop - 7]
                sampled[index].append(float(value))
        return tuple(tuple(values) for values in sampled)
    finally:
        scene.frame_set(min(max(original_frame, scene.frame_start), scene.frame_end))


def _entry_template_path(entry) -> str:
    if entry.template_path.strip():
        return entry.template_path
    action = _entry_action(entry)
    if action is not None:
        saved = (
            action.get("gbfr_mot_template_path")
            or action.get("gbfr_mot_imported_from_unpack")
        )
        if saved:
            entry.template_path = str(saved)
            return entry.template_path
    return entry.source_path or entry.path


def _entry_source_preview_path(entry) -> str:
    return entry.source_path or entry.path


def _entry_unpack_path(armature, entry) -> Path:
    cached = entry.unpack_path.strip()
    if cached:
        destination = Path(bpy.path.abspath(cached)).expanduser().resolve()
        if destination.suffix.casefold() == ".mot" and not destination.is_dir():
            return destination

    state = armature.gbfr_animation
    if not state.minfo_path.strip():
        raise ValueError("当前动画会话没有 minfo 路径；请刷新工作区后重试")
    bundle = resolve_model_bundle(state.minfo_path)
    asset = next(
        (
            candidate for candidate in bundle.animations
            if candidate.name.casefold() == entry.name.casefold()
        ),
        None,
    )
    if asset is None:
        raise ValueError(
            f"workspace 中找不到动画 {entry.name}；请刷新动画列表后重试"
        )
    destination = asset.unpack.expanduser().resolve()
    if destination.suffix.casefold() != ".mot" or destination.is_dir():
        raise ValueError(f"workspace 计算出的 MOT 输出目标无效: {destination}")
    entry.unpack_path = str(destination)
    if asset.source is not None:
        entry.source_path = str(asset.source)
    action = _entry_action(entry)
    if action is not None:
        action["gbfr_mot_unpack_path"] = str(destination)
    return destination


def _sample_bound_basis_for_clip(armature, clip: AnimationClip, scene):
    runtime = _make_runtime(armature, clip)
    result = {
        runtime["mapping"][bone_id]: ([], [], [])
        for bone_id in runtime["tracks"]
    }
    previous_rotations = {}
    original_frame = scene.frame_current
    try:
        for frame in range(clip.frame_count):
            scene.frame_set(frame)
            for bone_id in runtime["tracks"]:
                name = runtime["mapping"][bone_id]
                location, rotation, scale = armature.pose.bones[name].matrix_basis.decompose()
                rotation.normalize()
                previous = previous_rotations.get(name)
                if previous is not None:
                    rotation.make_compatible(previous)
                previous_rotations[name] = rotation.copy()
                result[name][0].append(tuple(location))
                result[name][1].append(tuple(rotation))
                result[name][2].append(tuple(scale))
        return result
    finally:
        scene.frame_set(min(max(original_frame, scene.frame_start), scene.frame_end))


class GBFR_OT_AnimationImportAction(Operator):
    bl_idname = "gbfr.animation_import_action"
    bl_label = "导入为可编辑 Action"
    bl_description = "将这一条 MOT 的全部可写回轨道逐帧烘焙为独立 Action"
    bl_options = {"REGISTER", "UNDO"}

    animation_index: IntProperty()

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_animation
        if not 0 <= self.animation_index < len(state.animations):
            return {"CANCELLED"}
        entry = state.animations[self.animation_index]
        previous = _action_entry(state, state.active_action_name)
        created = None
        passthrough = ()
        try:
            action = _entry_action(entry)
            if action is None:
                clip = load_mot(_entry_template_path(entry))
                samples, passthrough = _clip_basis_samples(armature, clip)
                _stop_preview(armature)
                action = _create_action_from_basis_samples(
                    armature, state, entry, samples, _ROLE_BASE, "Base",
                )
                created = action
                entry.action_name = action.name
                entry.passthrough_track_count = len(passthrough)
                action["gbfr_mot_passthrough_tracks"] = len(passthrough)
            state.active_animation_index = self.animation_index
            _bind_entry_action(armature, entry, context.scene)
            clip = load_mot(_entry_template_path(entry))
            error, projection_error = _validate_bound_action(
                armature, entry, clip, context.scene,
            )
            state.last_status = (
                f"已导入并激活 {entry.display_name}：{entry.frame_count} 帧，"
                f"Action 误差 {error:.2g}，源矩阵 TRS 投影 {projection_error:.2g}；"
                "源 MOT 直接预览已禁用"
            )
            if passthrough:
                state.last_status += f"；原样保留 {len(passthrough)} 条不可编辑轨道"
            self.report({"INFO"}, state.last_status)
            return {"FINISHED"}
        except Exception as error:
            if created is not None:
                if state.active_action_name == created.name:
                    _detach_action_stack(armature)
                    state.active_action_name = ""
                entry.action_name = ""
                bpy.data.actions.remove(created)
            if previous is not None and _entry_action(previous) is not None:
                _bind_entry_action(armature, previous, context.scene)
            state.last_status = str(error)
            self.report({"ERROR"}, state.last_status)
            return {"CANCELLED"}


class GBFR_OT_AnimationActivateAction(Operator):
    bl_idname = "gbfr.animation_activate_action"
    bl_label = "切换到此 Action"
    bl_options = {"REGISTER", "UNDO"}

    animation_index: IntProperty()

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_animation
        if not 0 <= self.animation_index < len(state.animations):
            return {"CANCELLED"}
        entry = state.animations[self.animation_index]
        try:
            state.active_animation_index = self.animation_index
            _bind_entry_action(armature, entry, context.scene)
            state.last_status = f"当前编辑 {entry.display_name}"
            return {"FINISHED"}
        except Exception as error:
            state.last_status = str(error)
            self.report({"ERROR"}, state.last_status)
            return {"CANCELLED"}


class GBFR_OT_AnimationValidateAction(Operator):
    bl_idname = "gbfr.animation_validate_action"
    bl_label = "验证当前 MOT"
    bl_description = "采样当前 Base/Edit 合成结果并检查是否可按模板写回"

    animation_index: IntProperty(default=-1)

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_animation
        index = self.animation_index if self.animation_index >= 0 else state.active_animation_index
        if not 0 <= index < len(state.animations):
            return {"CANCELLED"}
        entry = state.animations[index]
        previous = _action_entry(state, state.active_action_name)
        try:
            _bind_entry_action(armature, entry, context.scene)
            clip = load_mot(_entry_template_path(entry))
            _entry_unpack_path(armature, entry)
            sampled = _sample_bound_action_for_template(armature, clip, context.scene)
            if len(sampled) != len(clip.tracks):
                raise ValueError("Action 采样轨道数量不一致")
            entry.validation_status = "可导出"
            state.last_status = f"{entry.display_name} 验证通过：{len(sampled)} 轨 / {clip.frame_count} 帧"
            self.report({"INFO"}, state.last_status)
            return {"FINISHED"}
        except Exception as error:
            entry.validation_status = "失败"
            state.last_status = str(error)
            self.report({"ERROR"}, state.last_status)
            return {"CANCELLED"}
        finally:
            if previous is not None and previous != entry and _entry_action(previous) is not None:
                _bind_entry_action(armature, previous, context.scene)


class GBFR_OT_AnimationExportAction(Operator):
    bl_idname = "gbfr.animation_export_action"
    bl_label = "导出此 MOT 到 unpack"
    bl_description = "独立采样这一条 Action/NLA 并原子写入其 unpack MOT"

    animation_index: IntProperty()

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_animation
        if not 0 <= self.animation_index < len(state.animations):
            return {"CANCELLED"}
        entry = state.animations[self.animation_index]
        previous = _action_entry(state, state.active_action_name)
        try:
            _bind_entry_action(armature, entry, context.scene)
            clip = load_mot(_entry_template_path(entry))
            sampled = _sample_bound_action_for_template(armature, clip, context.scene)
            destination = write_mot_template_atomic(
                clip, sampled, _entry_unpack_path(armature, entry),
            )
            entry.export_exists = True
            entry.validation_status = "已导出"
            state.last_status = f"已独立导出 {entry.display_name} 到 {destination}"
            self.report({"INFO"}, state.last_status)
            return {"FINISHED"}
        except Exception as error:
            entry.validation_status = "失败"
            state.last_status = str(error)
            self.report({"ERROR"}, state.last_status)
            return {"CANCELLED"}
        finally:
            if previous is not None and previous != entry and _entry_action(previous) is not None:
                _bind_entry_action(armature, previous, context.scene)


class GBFR_OT_AnimationToggleExportPreview(Operator):
    bl_idname = "gbfr.animation_toggle_export_preview"
    bl_label = "切换导出 MOT 预览"
    bl_description = "直接预览 unpack 中已写出的 MOT；再次点击返回 Action 编辑"

    animation_index: IntProperty()

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_animation
        if not 0 <= self.animation_index < len(state.animations):
            return {"CANCELLED"}
        entry = state.animations[self.animation_index]
        try:
            if (
                state.export_preview_active
                and state.export_preview_entry_name == entry.name
            ):
                _stop_preview(armature)
                previous = _action_entry(state, state.active_action_name)
                if previous is not None and _entry_action(previous) is not None:
                    _bind_entry_action(armature, previous, context.scene)
                    state.last_status = f"已返回 Action 编辑：{previous.display_name}"
                elif not _has_imported_actions(state):
                    state.suspend_updates = True
                    state.active_animation_index = self.animation_index
                    state.suspend_updates = False
                    load_selected_animation(armature, context.scene)
                else:
                    state.last_status = "已结束导出 MOT 预览"
                return {"FINISHED"}

            destination = _entry_unpack_path(armature, entry)
            if not destination.is_file():
                entry.export_exists = False
                raise ValueError(f"尚未找到已导出的 MOT: {destination}")
            if context.screen and context.screen.is_animation_playing:
                bpy.ops.screen.animation_cancel(restore_frame=False)
            _detach_action_stack(armature)
            state.suspend_updates = True
            state.active_animation_index = self.animation_index
            state.suspend_updates = False
            clip = load_mot(destination)
            _start_runtime_preview(
                armature, context.scene, clip, exported_entry_name=entry.name,
            )
            entry.export_exists = True
            state.last_status = (
                f"正在预览已导出 MOT：{destination.name}；Action/NLA 已临时解除"
            )
            self.report({"INFO"}, state.last_status)
            return {"FINISHED"}
        except Exception as error:
            state.last_status = str(error)
            self.report({"ERROR"}, state.last_status)
            return {"CANCELLED"}


class GBFR_OT_AnimationReimportExported(Operator):
    bl_idname = "gbfr.animation_reimport_exported"
    bl_label = "导回导出的 MOT"
    bl_description = "将 unpack MOT 重新烘焙为 Base Action，并替换当前 Base/Edit"
    bl_options = {"REGISTER", "UNDO"}

    animation_index: IntProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_animation
        if not 0 <= self.animation_index < len(state.animations):
            return {"CANCELLED"}
        entry = state.animations[self.animation_index]
        old_base = _entry_action(entry)
        old_edit = _entry_edit_action(entry)
        previous = _action_entry(state, state.active_action_name)
        old_values = {
            "template_path": entry.template_path,
            "action_name": entry.action_name,
            "edit_action_name": entry.edit_action_name,
            "frame_count": entry.frame_count,
            "track_count": entry.track_count,
            "internal_name": entry.internal_name,
            "passthrough_track_count": entry.passthrough_track_count,
            "validation_status": entry.validation_status,
        }
        imported = None
        try:
            destination = _entry_unpack_path(armature, entry)
            if not destination.is_file():
                entry.export_exists = False
                raise ValueError(f"尚未找到已导出的 MOT: {destination}")
            clip = load_mot(destination)
            samples, passthrough = _clip_basis_samples(armature, clip)
            if state.export_preview_active:
                _stop_preview(armature)
            _detach_action_stack(armature)
            entry.template_path = str(destination)
            entry.frame_count = clip.frame_count
            entry.track_count = len(clip.tracks)
            entry.internal_name = clip.name
            imported = _create_action_from_basis_samples(
                armature, state, entry, samples, _ROLE_BASE, "Exported",
            )
            imported["gbfr_mot_passthrough_tracks"] = len(passthrough)
            imported["gbfr_mot_imported_from_unpack"] = str(destination)
            imported["gbfr_mot_template_path"] = str(destination)
            entry.action_name = imported.name
            entry.edit_action_name = ""
            entry.passthrough_track_count = len(passthrough)
            state.suspend_updates = True
            state.active_animation_index = self.animation_index
            state.suspend_updates = False
            _bind_entry_action(armature, entry, context.scene)
            action_error, projection_error = _validate_bound_action(
                armature, entry, clip, context.scene,
            )
            if old_edit is not None:
                bpy.data.actions.remove(old_edit)
            if old_base is not None:
                bpy.data.actions.remove(old_base)
            entry.export_exists = True
            entry.validation_status = "已从 unpack 导回"
            state.last_status = (
                f"已导回 {destination.name} 为新 Base Action；"
                f"Action 误差 {action_error:.2g}，TRS 投影 {projection_error:.2g}"
            )
            if passthrough:
                state.last_status += f"；原样保留 {len(passthrough)} 条不可编辑轨道"
            self.report({"INFO"}, state.last_status)
            return {"FINISHED"}
        except Exception as error:
            _detach_action_stack(armature)
            for name, value in old_values.items():
                setattr(entry, name, value)
            if imported is not None and bpy.data.actions.get(imported.name) is not None:
                bpy.data.actions.remove(imported)
            if old_base is not None and bpy.data.actions.get(old_base.name) is not None:
                _bind_entry_action(armature, entry, context.scene)
            elif (
                previous is not None and _entry_action(previous) is not None
                and previous != entry
            ):
                _bind_entry_action(armature, previous, context.scene)
            state.last_status = str(error)
            self.report({"ERROR"}, state.last_status)
            return {"CANCELLED"}


class GBFR_OT_AnimationRemoveAction(Operator):
    bl_idname = "gbfr.animation_remove_action"
    bl_label = "移除可编辑 Action"
    bl_description = "从当前 .blend 移除此 MOT 的 Base 和 Edit Action；不会删除 MOT 文件"
    bl_options = {"REGISTER", "UNDO"}

    animation_index: IntProperty()

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_animation
        if not 0 <= self.animation_index < len(state.animations):
            return {"CANCELLED"}
        entry = state.animations[self.animation_index]
        base = _entry_action(entry)
        edit = _entry_edit_action(entry)
        if base is None:
            return {"CANCELLED"}
        if state.export_preview_active:
            _stop_preview(armature)
        if state.active_action_name == base.name:
            _detach_action_stack(armature)
            state.active_action_name = ""
            _reset_pose(armature)
        entry.action_name = ""
        entry.edit_action_name = ""
        entry.template_path = ""
        if entry.source_path:
            entry.path = entry.source_path
        entry.passthrough_track_count = 0
        entry.validation_status = ""
        if edit is not None:
            bpy.data.actions.remove(edit)
        bpy.data.actions.remove(base)
        if _has_imported_actions(state):
            state.last_status = f"已移除 {entry.display_name} Action；源 MOT 直接预览仍禁用"
        else:
            state.last_status = f"已移除最后一个 Action；源 MOT 预览已重新启用"
        return {"FINISHED"}


class GBFR_OT_AnimationAddEditLayer(Operator):
    bl_idname = "gbfr.animation_add_edit_layer"
    bl_label = "添加 MOT 编辑层"
    bl_description = "在当前 Base Action 上增加唯一一条 COMBINE 编辑层"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_animation
        entry = _action_entry(state, state.active_action_name)
        if entry is None:
            self.report({"ERROR"}, "请先导入并激活一个 MOT Action")
            return {"CANCELLED"}
        if _entry_edit_action(entry) is not None:
            self.report({"ERROR"}, "当前 MOT 已有一条编辑层")
            return {"CANCELLED"}
        edit = bpy.data.actions.new(
            name=f"GBFR MOT | {state.model_id} | {entry.display_name} | Edit"
        )
        _tag_action(edit, state, entry, _ROLE_EDIT)
        edit.use_frame_range = True
        edit.frame_start = 0
        edit.frame_end = max(0, int(entry.frame_count) - 1)
        entry.edit_action_name = edit.name
        entry.validation_status = ""
        try:
            _bind_entry_action(armature, entry, context.scene)
        except Exception:
            entry.edit_action_name = ""
            bpy.data.actions.remove(edit)
            raise
        state.last_status = (
            f"已为 {entry.display_name} 添加一条 COMBINE 编辑层；"
            "直接在 Pose Mode 插入关键帧即可叠加修改"
        )
        return {"FINISHED"}


class GBFR_OT_AnimationDeleteEditLayer(Operator):
    bl_idname = "gbfr.animation_delete_edit_layer"
    bl_label = "删除 MOT 编辑层"
    bl_description = "放弃当前 MOT 的额外编辑层并恢复 Base Action"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_animation
        entry = _action_entry(state, state.active_action_name)
        edit = _entry_edit_action(entry) if entry is not None else None
        if entry is None or edit is None:
            return {"CANCELLED"}
        _detach_action_stack(armature)
        entry.edit_action_name = ""
        entry.validation_status = ""
        bpy.data.actions.remove(edit)
        _bind_entry_action(armature, entry, context.scene)
        state.last_status = f"已删除 {entry.display_name} 的额外编辑层"
        return {"FINISHED"}


class GBFR_OT_AnimationMergeEditLayer(Operator):
    bl_idname = "gbfr.animation_merge_edit_layer"
    bl_label = "合并 MOT 编辑层"
    bl_description = "逐帧烘焙 Base 与 Edit 的最终结果并替换当前 Base Action"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            return {"CANCELLED"}
        state = armature.gbfr_animation
        entry = _action_entry(state, state.active_action_name)
        base = _entry_action(entry) if entry is not None else None
        edit = _entry_edit_action(entry) if entry is not None else None
        if entry is None or base is None or edit is None:
            self.report({"ERROR"}, "当前 MOT 没有可合并的编辑层")
            return {"CANCELLED"}
        merged = None
        try:
            _bind_entry_action(armature, entry, context.scene)
            clip = load_mot(_entry_template_path(entry))
            samples = _sample_bound_basis_for_clip(armature, clip, context.scene)
            merged = _create_action_from_basis_samples(
                armature, state, entry, samples, _ROLE_BASE, "Merged",
            )
            merged["gbfr_mot_passthrough_tracks"] = int(
                entry.passthrough_track_count
            )
            _detach_action_stack(armature)
            entry.action_name = merged.name
            entry.edit_action_name = ""
            entry.validation_status = ""
            _bind_entry_action(armature, entry, context.scene)
            bpy.data.actions.remove(edit)
            bpy.data.actions.remove(base)
            state.last_status = f"已逐帧合并 {entry.display_name} 的 Base + Edit"
            return {"FINISHED"}
        except Exception as error:
            entry.action_name = base.name
            entry.edit_action_name = edit.name
            if merged is not None and bpy.data.actions.get(merged.name) is not None:
                bpy.data.actions.remove(merged)
            if bpy.data.actions.get(base.name) is not None and bpy.data.actions.get(edit.name) is not None:
                _bind_entry_action(armature, entry, context.scene)
            state.last_status = str(error)
            self.report({"ERROR"}, state.last_status)
            return {"CANCELLED"}


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
        state = armature.gbfr_animation
        if state.export_preview_active:
            if not state.preview_active:
                return {"CANCELLED"}
        elif _has_imported_actions(state):
            if not state.active_action_name or bpy.data.actions.get(state.active_action_name) is None:
                self.report({"ERROR"}, "请先切换到一个已导入 Action")
                return {"CANCELLED"}
        elif not state.preview_active:
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
        state = armature.gbfr_animation
        if state.export_preview_active:
            preview_entry = next(
                (
                    entry for entry in state.animations
                    if entry.name == state.export_preview_entry_name
                ),
                None,
            )
            _stop_preview(armature)
            previous = _action_entry(state, state.active_action_name)
            if previous is not None and _entry_action(previous) is not None:
                _bind_entry_action(armature, previous, context.scene)
                state.last_status = f"已停止导出预览并返回 {previous.display_name}"
            else:
                state.last_status = (
                    f"已停止 {preview_entry.display_name} 的导出预览"
                    if preview_entry is not None else "已停止导出 MOT 预览"
                )
        elif _has_imported_actions(state):
            state.last_status = "已停止 Action/NLA 时间轴播放"
        else:
            _stop_preview(armature)
            state.last_status = "静止姿态；点击动画条目重新预览"
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


def _entry_annotation(item) -> str:
    return guess_mot_annotation(item.name or item.display_name)


def _entry_has_exported_file(item) -> bool:
    cached = item.unpack_path.strip()
    if cached:
        return Path(bpy.path.abspath(cached)).expanduser().is_file()
    return item.export_exists


class GBFR_UL_Animations(UIList):
    def draw_item(self, _context, layout, data, item, _icon, _active_data, _active_propname, index):
        row = layout.row(align=True)
        action = _entry_action(item)
        active = action is not None and data.active_action_name == action.name
        annotation = _entry_annotation(item)
        display_name = item.display_name
        if annotation:
            display_name += f"  [推测：{annotation}]"
        row.label(text=display_name, icon="CHECKMARK" if active else "ACTION")
        row.label(text=f"{item.frame_count}帧")
        if _entry_has_exported_file(item):
            previewing_export = (
                data.export_preview_active
                and data.export_preview_entry_name == item.name
            )
            operator = row.operator(
                "gbfr.animation_toggle_export_preview", text="",
                icon="LOOP_BACK" if previewing_export else "FILE_MOVIE",
            )
            operator.animation_index = index
            operator = row.operator(
                "gbfr.animation_reimport_exported", text="", icon="IMPORT",
            )
            operator.animation_index = index
        if action is None:
            operator = row.operator("gbfr.animation_import_action", text="", icon="IMPORT")
            operator.animation_index = index
        elif not active:
            operator = row.operator(
                "gbfr.animation_activate_action", text="", icon="ACTION_TWEAK",
            )
            operator.animation_index = index
        if action is not None:
            operator = row.operator("gbfr.animation_export_action", text="", icon="EXPORT")
            operator.animation_index = index
            operator = row.operator("gbfr.animation_remove_action", text="", icon="X")
            operator.animation_index = index

    def filter_items(self, _context, data, property_name):
        values = getattr(data, property_name)
        query = data.search.strip().casefold()
        flags = [
            self.bitflag_filter_item
            if (
                not query
                or query in item.display_name.casefold()
                or query in item.internal_name.casefold()
                or query in _entry_annotation(item).casefold()
            )
            else 0
            for item in values
        ]
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
        row.operator("gbfr.animation_refresh", text="", icon="FILE_REFRESH")
        layout.template_list("GBFR_UL_Animations", "", state, "animations", state, "active_animation_index", rows=10)
        controls = layout.row(align=True)
        controls.operator("gbfr.animation_play_pause", text="", icon="PAUSE" if context.screen and context.screen.is_animation_playing else "PLAY")
        controls.operator("gbfr.animation_first_frame", text="", icon="REW")
        controls.operator("gbfr.animation_stop", text="", icon="CANCEL")
        imported = _has_imported_actions(state)
        if state.export_preview_active:
            controls.label(text="导出 MOT", icon="FILE_MOVIE")
        elif imported:
            controls.label(text="Action/NLA", icon="NLA")
        else:
            controls.label(text="源 MOT", icon="FILE_MOVIE")
        if state.animations:
            item = state.animations[state.active_animation_index]
            annotation = _entry_annotation(item)
            details = layout.row(align=True)
            details.label(text=item.internal_name or item.display_name, icon="ACTION")
            details.label(text=f"{item.frame_count}帧 · {item.track_count}轨")
            if annotation:
                layout.label(
                    text=f"文件名推测：{annotation}", icon="QUESTION",
                )
            if state.preview_active or imported:
                layout.prop(context.scene, "frame_current", text="帧")
        if imported:
            info = layout.box()
            if state.export_preview_active:
                info.label(
                    text="正在直接预览 unpack MOT；Action/NLA 暂时解除",
                    icon="FILE_MOVIE",
                )
            else:
                info.label(text="已有可编辑 Action，源 MOT 直接预览已禁用", icon="LOCKED")
            active_entry = _action_entry(state, state.active_action_name)
            if active_entry is not None and not state.export_preview_active:
                info.label(text=f"当前编辑：{active_entry.display_name}", icon="ACTION")
                if active_entry.validation_status:
                    info.label(text=active_entry.validation_status, icon="CHECKMARK")
                if active_entry.passthrough_track_count:
                    info.label(
                        text=f"{active_entry.passthrough_track_count} 条不可编辑轨道原样保留",
                        icon="INFO",
                    )
                tools = info.row(align=True)
                validate = tools.operator("gbfr.animation_validate_action", text="验证", icon="CHECKMARK")
                validate.animation_index = next(
                    index for index, entry in enumerate(state.animations) if entry == active_entry
                )
                if _entry_edit_action(active_entry) is None:
                    tools.operator("gbfr.animation_add_edit_layer", text="添加编辑层", icon="ADD")
                else:
                    tools.operator("gbfr.animation_merge_edit_layer", text="合并编辑层", icon="AUTOMERGE_ON")
                    tools.operator("gbfr.animation_delete_edit_layer", text="删除编辑层", icon="REMOVE")


classes = (
    GBFRAnimationEntryProperties, GBFRAnimationStateProperties,
    GBFR_OT_AnimationImportAction, GBFR_OT_AnimationActivateAction,
    GBFR_OT_AnimationValidateAction, GBFR_OT_AnimationExportAction,
    GBFR_OT_AnimationToggleExportPreview,
    GBFR_OT_AnimationReimportExported,
    GBFR_OT_AnimationRemoveAction,
    GBFR_OT_AnimationAddEditLayer, GBFR_OT_AnimationDeleteEditLayer,
    GBFR_OT_AnimationMergeEditLayer,
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
