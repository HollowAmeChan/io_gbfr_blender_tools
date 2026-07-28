"""Run with: blender --background --python this_file.py -- path/to/unpack/fpXXXX.minfo [mot_name]"""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Quaternion, Vector


separator = sys.argv.index("--")
minfo = Path(sys.argv[separator + 1]).resolve()
requested_name = sys.argv[separator + 2] if len(sys.argv) > separator + 2 else "fp1400_000b"

bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
assert bpy.ops.gbfr.import_mesh(filepath=str(minfo), import_scale=1.0) == {"FINISHED"}

from io_gbfr_blender_tools.gbfr_animation import load_mot
import io_gbfr_blender_tools.gbfr_animation_blender as animation_blender
from io_gbfr_blender_tools.gbfr_animation_blender import (
    _ACTION_BASIS_KIND, _BASIS_SOURCE_ABSOLUTE, _ROLE_BASE,
    _action_basis_kind, _action_bone_basis_samples, _action_rebased_bones,
    _action_revision, _entry_action, _entry_edit_action, _find_saved_action,
    _make_runtime, _project_trs, _sample_local_matrix,
    _workspace_skeleton_path,
)
from io_gbfr_blender_tools.gbfr_session import active_session_armature
from io_gbfr_blender_tools.gbfr_workspace import (
    find_workspace_json, resolve_model_export_targets,
)


def matrix_error(left, right):
    return max(
        abs(left[row][column] - right[row][column])
        for row in range(4) for column in range(4)
    )


def rest_matrix(rest):
    return Matrix.LocRotScale(
        Vector(rest["position"]), Quaternion(rest["rotation"]), Vector(rest["scale"]),
    )


def select_only(armature, bone_id):
    for bone in armature.data.bones:
        bone.select = int(bone.get("gbfr_bone_id", -1)) == bone_id


armature = active_session_armature(bpy.context)
assert armature is not None
state = armature.gbfr_animation
workspace = find_workspace_json(minfo)
expected_targets = resolve_model_export_targets(workspace, minfo.stem)
state.workspace_path = ""
state.model_id = "__stale_model_id__"
assert _workspace_skeleton_path(armature, "source").resolve() == (
    expected_targets.reference_skeleton.resolve()
)
assert _workspace_skeleton_path(armature, "unpack").resolve() == (
    expected_targets.skeleton.resolve()
)
assert Path(state.workspace_path).resolve() == workspace.resolve()
assert state.model_id == minfo.stem
index = next(
    index for index, entry in enumerate(state.animations)
    if entry.display_name == requested_name
)
entry = state.animations[index]
clip = load_mot(entry.source_path or entry.path)
runtime = _make_runtime(armature, clip, rest_area="source")
candidate_ids = [
    bone_id for bone_id in sorted(runtime["tracks"])
    if all(prop in {track.property for track in runtime["tracks"][bone_id]} for prop in range(3))
]
assert len(candidate_ids) >= 3
first_id, second_id, untouched_id = candidate_ids[:3]

select_only(armature, first_id)
assert _entry_action(entry) is None
assert bpy.ops.gbfr.animation_rebase_selected_bones(animation_index=index) == {"FINISHED"}
action = _entry_action(entry)
assert action is not None
assert _action_basis_kind(action) == _BASIS_SOURCE_ABSOLUTE
assert _action_rebased_bones(action) == {first_id}
assert all(
    _entry_action(other) is None
    for other_index, other in enumerate(state.animations)
    if other_index != index
)

first_name = runtime["mapping"][first_id]
first_rest = runtime["rest"][first_id]
first_source_local = _sample_local_matrix(
    first_rest, runtime["tracks"][first_id], 0,
)
expected_relative = _project_trs(
    rest_matrix(first_rest).inverted_safe() @ first_source_local,
)
first_actual = _action_bone_basis_samples(
    action, armature.pose.bones[first_name], clip.frame_count,
)[0]
assert matrix_error(first_actual, expected_relative) < 2e-5

untouched_name = runtime["mapping"][untouched_id]
untouched_rest = runtime["rest"][untouched_id]
untouched_source_local = _sample_local_matrix(
    untouched_rest, runtime["tracks"][untouched_id], 0,
)
expected_absolute_preview = _project_trs(
    untouched_rest["rest_inverse"] @ untouched_source_local,
)
untouched_before = _action_bone_basis_samples(
    action, armature.pose.bones[untouched_name], clip.frame_count,
)[0]
assert matrix_error(untouched_before, expected_absolute_preview) < 2e-5

assert bpy.ops.gbfr.animation_rebase_selected_bones(animation_index=index) == {"FINISHED"}
action = _entry_action(entry)
first_repeated = _action_bone_basis_samples(
    action, armature.pose.bones[first_name], clip.frame_count,
)[0]
assert matrix_error(first_actual, first_repeated) < 1e-8

original_skeleton_path = animation_blender._workspace_skeleton_path
animation_blender._workspace_skeleton_path = (
    lambda _armature, _area: minfo.with_name("__missing_source__.skeleton")
)
select_only(armature, second_id)
try:
    bpy.ops.gbfr.animation_rebase_selected_bones(animation_index=index)
    raise AssertionError("missing source skeleton was accepted")
except RuntimeError as error:
    assert "找到 source skeleton" in str(error)
animation_blender._workspace_skeleton_path = original_skeleton_path
assert _entry_action(entry) == action
assert _action_rebased_bones(action) == {first_id}

saved_basis_kind = action[_ACTION_BASIS_KIND]
del action[_ACTION_BASIS_KIND]
select_only(armature, second_id)
try:
    bpy.ops.gbfr.animation_rebase_selected_bones(animation_index=index)
    raise AssertionError("unversioned Action was accepted")
except RuntimeError as error:
    assert "缺少基准版本" in str(error)
assert _entry_action(entry) == action
assert _action_rebased_bones(action) == {first_id}
action[_ACTION_BASIS_KIND] = saved_basis_kind

assert bpy.ops.gbfr.animation_add_edit_layer() == {"FINISHED"}
edit_action = _entry_edit_action(entry)
assert edit_action is not None
shared_user = bpy.data.objects.new("GBFR rebase shared-action observer", None)
bpy.context.scene.collection.objects.link(shared_user)
shared_user.animation_data_create().action = action
shared_action = action
shared_name = shared_action.name
shared_role = shared_action.get("gbfr_mot_role")
shared_revision = _action_revision(shared_action)

second_name = runtime["mapping"][second_id]
second_pose_bone = armature.pose.bones[second_name]
location_path = second_pose_bone.path_from_id("location")
location_curve = action.fcurves.find(location_path, index=0)
assert location_curve is not None
point_at_zero = next(point for point in location_curve.keyframe_points if abs(point.co.x) < 1e-6)
point_at_zero.co.y += 0.01
location_curve.update()
second_actual_before = _action_bone_basis_samples(
    action, second_pose_bone, clip.frame_count,
)[0]
second_rest = runtime["rest"][second_id]
second_source_local = _sample_local_matrix(
    second_rest, runtime["tracks"][second_id], 0,
)
second_wrong = _project_trs(second_rest["rest_inverse"] @ second_source_local)
second_relative = _project_trs(
    rest_matrix(second_rest).inverted_safe() @ second_source_local,
)
expected_with_edit = _project_trs(
    second_relative @ second_wrong.inverted_safe() @ second_actual_before,
)

select_only(armature, second_id)
assert bpy.ops.gbfr.animation_rebase_selected_bones(animation_index=index) == {"FINISHED"}
action = _entry_action(entry)
assert _action_rebased_bones(action) == {first_id, second_id}
assert action != shared_action
assert shared_user.animation_data.action == shared_action
assert shared_action.name == shared_name
assert shared_action.get("gbfr_mot_role") == shared_role
assert _action_revision(shared_action) == shared_revision
assert _action_rebased_bones(shared_action) == {first_id}
assert _action_revision(action) == shared_revision + 1
assert _find_saved_action(state, entry.name, _ROLE_BASE) == action
assert _entry_edit_action(entry) == edit_action
assert armature.animation_data.action == edit_action
assert len(armature.animation_data.nla_tracks) == 1
assert armature.animation_data.nla_tracks[0].strips[0].action == action
second_actual_after = _action_bone_basis_samples(
    action, second_pose_bone, clip.frame_count,
)[0]
assert matrix_error(second_actual_after, expected_with_edit) < 2e-5
untouched_after = _action_bone_basis_samples(
    action, armature.pose.bones[untouched_name], clip.frame_count,
)[0]
assert matrix_error(untouched_before, untouched_after) < 1e-8

bound_before_failure = action
foreign_action = bpy.data.actions.new("GBFR rebase rollback foreign Action")
armature.animation_data.action = foreign_action
armature.animation_data.action_blend_type = "ADD"
armature.animation_data.action_influence = 0.37
state.active_action_name = "__stale_action_name__"
original_bind = animation_blender._bind_entry_action
bind_calls = 0


def fail_after_bind(*args, **kwargs):
    global bind_calls
    bind_calls += 1
    original_bind(*args, **kwargs)
    if bind_calls == 1:
        raise RuntimeError("intentional rebase bind failure")


select_only(armature, untouched_id)
animation_blender._bind_entry_action = fail_after_bind
try:
    bpy.ops.gbfr.animation_rebase_selected_bones(animation_index=index)
    raise AssertionError("intentional bind failure was not reported")
except RuntimeError as error:
    assert "intentional rebase bind failure" in str(error)
animation_blender._bind_entry_action = original_bind
action = _entry_action(entry)
assert action == bound_before_failure
assert _action_rebased_bones(action) == {first_id, second_id}
assert _entry_edit_action(entry) == edit_action
assert armature.animation_data.action == foreign_action
assert armature.animation_data.action_blend_type == "ADD"
assert abs(armature.animation_data.action_influence - 0.37) < 1e-8
assert state.active_action_name == "__stale_action_name__"
assert len(armature.animation_data.nla_tracks) == 1
assert armature.animation_data.nla_tracks[0].strips[0].action == action
untouched_after_failure = _action_bone_basis_samples(
    action, armature.pose.bones[untouched_name], clip.frame_count,
)[0]
assert matrix_error(untouched_before, untouched_after_failure) < 1e-8
armature.animation_data.action = edit_action
armature.animation_data.action_blend_type = "COMBINE"
armature.animation_data.action_influence = 1.0
state.active_action_name = action.name

with tempfile.TemporaryDirectory(prefix="gbfr_mot_rebase_") as temporary:
    output = Path(temporary) / entry.name
    original_resolver = animation_blender.resolve_model_bundle
    animation_blender.resolve_model_bundle = lambda _path, _workspace=None: SimpleNamespace(
        workspace_json=workspace, model_id=minfo.stem,
        animations=(SimpleNamespace(
            name=entry.name, unpack=output, source=Path(entry.source_path),
        ),),
    )
    entry.unpack_path = ""
    assert bpy.ops.gbfr.animation_export_action(animation_index=index) == {"FINISHED"}
    exported = load_mot(output)
    source_untouched = {
        track.property: track for track in clip.tracks if track.bone_id == untouched_id
    }
    output_untouched = {
        track.property: track for track in exported.tracks if track.bone_id == untouched_id
    }
    assert source_untouched.keys() == output_untouched.keys()
    for prop in source_untouched:
        for frame in range(clip.frame_count):
            assert abs(
                source_untouched[prop].sample(frame) - output_untouched[prop].sample(frame)
            ) < 2e-5
    source_first = next(
        track for track in clip.tracks if track.bone_id == first_id and track.property == 2
    )
    output_first = next(
        track for track in exported.tracks if track.bone_id == first_id and track.property == 2
    )
    assert abs(source_first.sample(0) - output_first.sample(0)) > 1e-4
    output_first_positions = {
        track.property: track
        for track in exported.tracks
        if track.bone_id == first_id and track.property in {0, 1, 2}
    }
    assert output_first_positions.keys() == {0, 1, 2}
    source_rest_inverse = rest_matrix(first_rest).inverted_safe()
    for frame in range(clip.frame_count):
        source_local = _sample_local_matrix(
            first_rest, runtime["tracks"][first_id], frame,
        )
        expected_local = first_rest["rest_matrix"] @ source_rest_inverse @ source_local
        expected_location = expected_local.decompose()[0]
        for prop, track in output_first_positions.items():
            assert abs(track.sample(frame) - expected_location[prop]) < 3e-5
    animation_blender.resolve_model_bundle = original_resolver

print("GBFR selected-bone MOT rebase smoke passed")
