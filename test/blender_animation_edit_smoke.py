"""Run with: blender --background --python this_file.py -- path/to/source/fpXXXX.minfo"""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import bpy


separator = sys.argv.index("--")
minfo = Path(sys.argv[separator + 1]).resolve()
requested_names = tuple(sys.argv[separator + 2:])

bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
assert bpy.ops.gbfr.import_mesh(filepath=str(minfo), import_scale=1.0) == {"FINISHED"}

from io_gbfr_blender_tools.gbfr_animation import load_mot
from io_gbfr_blender_tools.gbfr_animation_blender import (
    _ACTIVE_CLIPS, _entry_action, _entry_annotation, _entry_edit_action,
    _entry_unpack_path, _has_imported_actions, load_selected_animation,
)
from io_gbfr_blender_tools.gbfr_session import active_session_armature


armature = active_session_armature(bpy.context)
assert armature is not None
state = armature.gbfr_animation
assert not armature.gbfr_cloth.enabled
assert len(armature.gbfr_cloth.clp_groups) == 0
assert len(armature.gbfr_cloth.clh_layers) == 0
annotations = {
    item.display_name: item.guessed_annotation for item in state.animations
}
assert annotations["fp1400_030a"] == "闭左眼"
assert annotations["fp1400_031a"] == "紧张闭眼"
assert annotations["fp1400_032a"] == "闭右眼"
assert annotations["fp1400_034a"] == "闭眼"
assert annotations["fp1400_035a"] == "紧闭眼"
assert annotations["fp1400_036a"] == "舒张闭眼"
assert annotations["fp1400_e00a"] == "闭眼笑"
e00a = next(item for item in state.animations if item.display_name == "fp1400_e00a")
assert _entry_annotation(e00a) == "闭眼笑"
assert all(
    annotation == "口型"
    for name, annotation in annotations.items()
    if "c50b" <= name.rsplit("_", 1)[-1] <= "c84b"
)
names = requested_names or ("fp1400_000a", "fp1400_000b")
assert len(names) == 2
indices = [
    next(index for index, item in enumerate(state.animations) if item.display_name == name)
    for name in names
]

state.active_animation_index = indices[0]
assert state.preview_active
assert bpy.ops.gbfr.animation_import_action(animation_index=indices[0]) == {"FINISHED"}
first = state.animations[indices[0]]
source_preview_path = Path(first.source_path or first.path).resolve()
first_base = _entry_action(first)
assert first_base is not None and not state.preview_active
assert _has_imported_actions(state)
clip = load_mot(first.path)
with tempfile.TemporaryDirectory(prefix="gbfr_mot_roundtrip_") as temporary:
    output = Path(temporary) / first.name
    import io_gbfr_blender_tools.gbfr_animation_blender as animation_blender

    original_resolver = animation_blender.resolve_model_bundle
    first.unpack_path = ""
    animation_blender.resolve_model_bundle = lambda _path: SimpleNamespace(
        animations=(SimpleNamespace(
            name=first.name, unpack=output, source=Path(first.source_path),
        ),),
    )
    try:
        assert _entry_unpack_path(armature, first) == output.resolve()
    finally:
        animation_blender.resolve_model_bundle = original_resolver
    assert bpy.ops.gbfr.animation_export_action(animation_index=indices[0]) == {"FINISHED"}
    exported = load_mot(output)
    assert first.export_exists
    assert bpy.ops.gbfr.animation_toggle_export_preview(
        animation_index=indices[0],
    ) == {"FINISHED"}
    assert state.preview_active and state.export_preview_active
    assert state.export_preview_entry_name == first.name
    assert armature.animation_data.action is None
    assert _ACTIVE_CLIPS[state.cache_key]["clip"].path == output.resolve()
    assert bpy.ops.gbfr.animation_toggle_export_preview(
        animation_index=indices[0],
    ) == {"FINISHED"}
    assert not state.preview_active and not state.export_preview_active
    assert armature.animation_data.action == first_base
    assert len(exported.tracks) == len(clip.tracks)
    for source_track, output_track in zip(clip.tracks, exported.tracks):
        assert (source_track.bone_id, source_track.property, source_track.unknown) == (
            output_track.bone_id, output_track.property, output_track.unknown,
        )
        for frame in range(clip.frame_count):
            assert abs(output_track.sample(frame) - source_track.sample(frame)) < 2e-5
try:
    load_selected_animation(armature, bpy.context.scene)
except ValueError as error:
    assert "直接预览已禁用" in str(error)
else:
    raise AssertionError("source preview remained available after importing an Action")

assert bpy.ops.gbfr.animation_import_action(animation_index=indices[1]) == {"FINISHED"}
second = state.animations[indices[1]]
second_base = _entry_action(second)
assert second_base is not None and second_base != first_base
assert state.active_action_name == second_base.name
assert sum(_entry_action(item) is not None for item in state.animations) == 2

assert bpy.ops.gbfr.animation_activate_action(animation_index=indices[0]) == {"FINISHED"}
assert state.active_action_name == first_base.name
assert armature.animation_data.action == first_base
assert bpy.ops.gbfr.animation_add_edit_layer() == {"FINISHED"}
edit = _entry_edit_action(first)
assert edit is not None and armature.animation_data.action == edit
assert armature.animation_data.action_blend_type == "COMBINE"
assert len(armature.animation_data.nla_tracks) == 1

probe_track = next(track for track in clip.tracks if track.property == 0 and track.bone_id >= 0)
probe_bone = next(
    bone for bone in armature.data.bones
    if int(bone.get("gbfr_bone_id", -1)) == probe_track.bone_id
)
pose_bone = armature.pose.bones[probe_bone.name]
bpy.context.scene.frame_set(0)
before = pose_bone.matrix_basis.copy()
pose_bone.location.x += 0.01
assert pose_bone.keyframe_insert(data_path="location", index=0, frame=0)
bpy.context.scene.frame_set(1)
bpy.context.scene.frame_set(0)
after = pose_bone.matrix_basis.copy()
assert abs(after.translation.x - before.translation.x) > 1e-4

with tempfile.TemporaryDirectory(prefix="gbfr_mot_edit_") as temporary:
    output = Path(temporary) / first.name
    first.unpack_path = str(output)
    assert bpy.ops.gbfr.animation_export_action(animation_index=indices[0]) == {"FINISHED"}
    assert output.is_file()
    exported = load_mot(output)
    assert (
        exported.version, exported.flags, exported.frame_count,
        exported.unknown, exported.name, len(exported.tracks),
    ) == (
        clip.version, clip.flags, clip.frame_count,
        clip.unknown, clip.name, len(clip.tracks),
    )
    source_probe = next(
        track for track in clip.tracks
        if track.bone_id == probe_track.bone_id and track.property == 0
    )
    output_probe = next(
        track for track in exported.tracks
        if track.bone_id == probe_track.bone_id and track.property == 0
    )
    assert abs(output_probe.sample(0) - source_probe.sample(0)) > 1e-5
    for source_track, output_track in zip(clip.tracks, exported.tracks):
        if source_track.bone_id == probe_track.bone_id:
            continue
        for frame in range(clip.frame_count):
            assert abs(output_track.sample(frame) - source_track.sample(frame)) < 2e-5

    old_base_name = first_base.name
    old_edit_name = edit.name
    assert bpy.ops.gbfr.animation_reimport_exported(
        animation_index=indices[0],
    ) == {"FINISHED"}
    reimported = _entry_action(first)
    assert reimported is not None and reimported.name != old_base_name
    reimported_name = reimported.name
    assert _entry_edit_action(first) is None
    assert bpy.data.actions.get(old_base_name) is None
    assert bpy.data.actions.get(old_edit_name) is None
    assert Path(first.template_path) == output.resolve()
    assert Path(first.path).resolve() == source_preview_path
    assert armature.animation_data.action == reimported
    assert bpy.ops.gbfr.animation_add_edit_layer() == {"FINISHED"}
    assert bpy.ops.gbfr.animation_merge_edit_layer() == {"FINISHED"}
    merged = _entry_action(first)
    assert merged is not None and merged.name != reimported_name
    assert _entry_edit_action(first) is None
    assert armature.animation_data.action == merged
    assert len(armature.animation_data.nla_tracks) == 0

assert bpy.ops.gbfr.animation_remove_action(animation_index=indices[1]) == {"FINISHED"}
assert _has_imported_actions(state)
assert bpy.ops.gbfr.animation_remove_action(animation_index=indices[0]) == {"FINISHED"}
assert not _has_imported_actions(state)
assert not first.template_path
assert Path(first.path).resolve() == source_preview_path
state.active_animation_index = indices[0]
load_selected_animation(armature, bpy.context.scene)
assert state.preview_active
assert _ACTIVE_CLIPS[state.cache_key]["clip"].path == source_preview_path

print("GBFR MOT Action/edit/export smoke passed")
