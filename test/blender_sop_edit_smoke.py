"""Run with: blender --background --factory-startup --python this_file.py"""

import json
from math import radians
from pathlib import Path
import tempfile

import bpy
from mathutils import Quaternion, Vector


bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")

from io_gbfr_blender_tools.gbfr_session import configure_session
from io_gbfr_blender_tools.gbfr_sop import (
    OFFSET_X_PROPERTY, OFFSET_Y_PROPERTY, OFFSET_Z_PROPERTY, SOP_VERSION,
    SWING_RATE_PROPERTY, SopAsset, evaluate_core_operation, load_sop,
    make_swing_twist_operation, quaternion_error, save_sop,
)
from io_gbfr_blender_tools.gbfr_sop_blender import (
    CONSTRAINT_PREFIX, DRIVER_EXPRESSION_PREFIX, GBFR_UL_SopOperations, _asset_from_state,
    _export_rest_quaternion, _model_export_ready, populate_sop_state,
    stage_sop_for_workspace,
)
from io_gbfr_blender_tools.gbfr_workspace import resolve_model_bundle


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    paths = {
        "source_minfo": "source/data/model/pl/pl9999/pl9999.minfo",
        "unpack_minfo": "unpack/data/model/pl/pl9999/pl9999.minfo",
        "source_sop": "source/data/model/pl/pl9999/pl9999.sop",
        "unpack_sop": "unpack/data/model/pl/pl9999/pl9999.sop",
        "source_mmesh": "source/data/model_streaming/lod0/pl9999.mmesh",
        "unpack_mmesh": "unpack/data/model_streaming/lod0/pl9999.mmesh",
    }
    for key in ("source_minfo", "unpack_minfo", "source_mmesh", "unpack_mmesh"):
        path = root / paths[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    source_sop = root / paths["source_sop"]
    save_sop(source_sop, SopAsset(
        source_sop, SOP_VERSION,
        (make_swing_twist_operation(0xA50, 0x00E, 1, 0.5, 0.0, index=0),),
    ))
    source_bytes = source_sop.read_bytes()
    workspace = {
        "Version": 1,
        "CharacterId": "pl9999",
        "ModelFiles": [
            {"FileType": "minfo", "Source": paths["source_minfo"], "Input": paths["unpack_minfo"]},
            {"FileType": "mmesh", "Source": paths["source_mmesh"], "Input": paths["unpack_mmesh"]},
            {"FileType": "sop", "Source": paths["source_sop"], "Input": paths["unpack_sop"]},
        ],
    }
    workspace_path = root / "workspace.json"
    workspace_path.write_text(json.dumps(workspace), encoding="utf-8")
    bundle = resolve_model_bundle(root / paths["source_minfo"], workspace_path)

    armature_data = bpy.data.armatures.new("SOP Armature")
    armature = bpy.data.objects.new("SOP Armature", armature_data)
    collection = bpy.data.collections.new("SOP Session")
    bpy.context.scene.collection.children.link(collection)
    collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    source_bone = armature.data.edit_bones.new("_00e")
    source_bone.head, source_bone.tail = (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    target_bone = armature.data.edit_bones.new("_a50")
    target_bone.head, target_bone.tail = (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)
    skirt_bone = armature.data.edit_bones.new("Skirt_B_01")
    skirt_bone.head, skirt_bone.tail = (2.0, 0.0, 0.0), (2.0, 0.0, 1.0)
    angled_skirt_bone = armature.data.edit_bones.new("Skirt_C_01")
    angled_skirt_bone.head, angled_skirt_bone.tail = (3.0, 0.0, 0.0), (4.0, 1.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, bone_id in (("_00e", 0x00E), ("_a50", 0xA50)):
        bone = armature.data.bones[name]
        bone["gbfr_bone_id"] = bone_id
        bone["gbfr_rest_quaternion"] = (1.0, 0.0, 0.0, 0.0)
    armature.data.bones["Skirt_B_01"]["gbfr_bone_id"] = 0xA51
    armature.data.bones["Skirt_C_01"]["gbfr_bone_id"] = 0xA52

    configure_session(
        collection, bundle, root / paths["source_minfo"],
        armature, armature, (), bpy.context.scene,
    )
    populate_sop_state(armature, bundle)
    state = armature.gbfr_sop
    assert state.enabled and len(state.operations) == 1
    assert not (root / paths["unpack_sop"]).exists()
    state.minfo_path = ""
    state.edit_path = ""
    state.source_baseline_path = ""
    assert not _model_export_ready(bpy.context, state)
    assert bpy.ops.gbfr.sop_reload() == {"FINISHED"}
    assert Path(state.minfo_path) == root / paths["source_minfo"]
    assert Path(state.edit_path) == root / paths["unpack_sop"]
    assert Path(state.source_baseline_path) == source_sop
    filter_proxy = type("FilterProxy", (), {"bitflag_filter_item": 1})()
    state.operation_search = "_a50"
    assert GBFR_UL_SopOperations.filter_items(
        filter_proxy, bpy.context, state, "operations",
    )[0] == [1]
    state.operation_search = "missing"
    assert GBFR_UL_SopOperations.filter_items(
        filter_proxy, bpy.context, state, "operations",
    )[0] == [0]
    state.operation_search = ""
    state.operation_filter = "READ_ONLY"
    assert GBFR_UL_SopOperations.filter_items(
        filter_proxy, bpy.context, state, "operations",
    )[0] == [0]
    state.operation_filter = "ALL"

    def sop_drivers(bone_name):
        data_path = armature.pose.bones[bone_name].path_from_id("rotation_quaternion")
        animation_data = armature.animation_data
        return [
            curve for curve in animation_data.drivers
            if curve.data_path == data_path
            and curve.driver.expression.startswith(DRIVER_EXPRESSION_PREFIX)
        ] if animation_data is not None else []

    def assert_exact_pose(operation, target_name, source_name):
        source_pose = armature.pose.bones[source_name]
        source_pose.rotation_quaternion = Quaternion(
            Vector((0.35, -0.2, 0.6)).normalized(), radians(23.0),
        )
        bpy.context.view_layer.update()
        evaluated = armature.evaluated_get(bpy.context.evaluated_depsgraph_get())
        actual_basis = tuple(evaluated.pose.bones[target_name].rotation_quaternion)
        source_rest = _export_rest_quaternion(armature, source_name)
        target_rest = _export_rest_quaternion(armature, target_name)
        source_local = source_rest @ source_pose.rotation_quaternion
        output = evaluate_core_operation(operation, tuple(source_local))
        expected_basis = target_rest.inverted() @ Quaternion(output)
        assert quaternion_error(actual_basis, tuple(expected_basis)) < 1e-5
        source_pose.rotation_quaternion = Quaternion((1.0, 0.0, 0.0, 0.0))
        bpy.context.view_layer.update()

    state.operations[0].editable = False
    assert bpy.ops.gbfr.sop_delete() == {"FINISHED"}
    assert len(state.operations) == 0, "只读 SOP 条目也应允许从列表删除"
    assert bpy.ops.gbfr.sop_reload() == {"FINISHED"}
    assert len(state.operations) == 1
    assert bpy.ops.gbfr.sop_add(
        constraint_type="SKIRT_COPY_ROTATION",
        target_ref="Skirt_B_01", source_ref="_00e", axis="1",
        swing_rate=0.75, twist_rate=0.25,
    ) == {"FINISHED"}
    assert len(state.operations) == 2
    assert state.active_operation_index == 1
    assert state.operations[1].preview_status == "exact_driver"
    skirt_constraints = [
        constraint for constraint in armature.pose.bones["Skirt_B_01"].constraints
        if constraint.name.startswith(CONSTRAINT_PREFIX)
    ]
    assert not skirt_constraints
    assert len(sop_drivers("Skirt_B_01")) == 4
    state.preview_constraints = False
    assert all(curve.mute for curve in sop_drivers("Skirt_B_01"))
    state.preview_constraints = True
    assert not any(curve.mute for curve in sop_drivers("Skirt_B_01"))

    authored = _asset_from_state(armature).operations[1]
    offset = tuple(authored.floating(value) for value in (
        OFFSET_X_PROPERTY, OFFSET_Y_PROPERTY, OFFSET_Z_PROPERTY,
    ))
    assert abs(offset[0]) > 1.0, offset
    source_rest = tuple(_export_rest_quaternion(armature, "_00e"))
    target_rest = tuple(_export_rest_quaternion(armature, "Skirt_B_01"))
    evaluated_rest = evaluate_core_operation(authored, source_rest)
    assert quaternion_error(evaluated_rest, target_rest) < 1e-5
    assert_exact_pose(authored, "Skirt_B_01", "_00e")
    assert bpy.ops.gbfr.sop_delete() == {"FINISHED"}
    assert len(state.operations) == 1
    assert not sop_drivers("Skirt_B_01")

    assert bpy.ops.gbfr.sop_add(
        constraint_type="SKIRT_COPY_ROTATION",
        target_ref="Skirt_C_01", source_ref="_00e", axis="1",
        swing_rate=0.75, twist_rate=0.25,
    ) == {"FINISHED"}
    assert state.operations[1].preview_status == "exact_driver"
    angled_constraints = [
        constraint for constraint in armature.pose.bones["Skirt_C_01"].constraints
        if constraint.name.startswith(CONSTRAINT_PREFIX)
    ]
    assert not angled_constraints
    assert len(sop_drivers("Skirt_C_01")) == 4
    angled_operation = _asset_from_state(armature).operations[1]
    assert_exact_pose(angled_operation, "Skirt_C_01", "_00e")
    assert bpy.ops.gbfr.sop_delete() == {"FINISHED"}
    assert len(state.operations) == 1
    assert not sop_drivers("Skirt_C_01")

    user_curve = armature.pose.bones["Skirt_C_01"].driver_add("rotation_quaternion", 0)
    user_curve.driver.expression = "1.0"
    assert bpy.ops.gbfr.sop_add(
        constraint_type="SKIRT_COPY_ROTATION",
        target_ref="Skirt_C_01", source_ref="_00e", axis="1",
        swing_rate=0.75, twist_rate=0.25,
    ) == {"FINISHED"}
    assert state.operations[1].preview_status == "approximate_unchecked"
    assert len([
        constraint for constraint in armature.pose.bones["Skirt_C_01"].constraints
        if constraint.name.startswith(CONSTRAINT_PREFIX)
    ]) == 2
    assert any(curve == user_curve for curve in armature.animation_data.drivers)
    assert bpy.ops.gbfr.sop_delete() == {"FINISHED"}
    assert any(curve == user_curve for curve in armature.animation_data.drivers)
    assert armature.pose.bones["Skirt_C_01"].driver_remove("rotation_quaternion", 0)

    assert bpy.ops.gbfr.sop_add(
        constraint_type="SKIRT_COPY_ROTATION",
        target_ref="Skirt_C_01", source_ref="_00e", axis="1",
        swing_rate=0.0, twist_rate=0.0,
    ) == {"FINISHED"}
    assert state.operations[1].preview_status == "zero_effect"
    assert not [
        constraint for constraint in armature.pose.bones["Skirt_C_01"].constraints
        if constraint.name.startswith(CONSTRAINT_PREFIX)
    ]
    assert bpy.ops.gbfr.sop_delete() == {"FINISHED"}
    assert len(state.operations) == 1

    item = state.operations[0]
    item.swing_rate = 0.6
    constraints = [
        constraint for bone in armature.pose.bones for constraint in bone.constraints
        if constraint.name.startswith(CONSTRAINT_PREFIX)
    ]
    assert not constraints
    assert len(sop_drivers("_a50")) == 4
    assert not (root / paths["unpack_sop"]).exists(), "Blender 内编辑不应自动写文件"

    staged = root / "staging/pl9999.sop"
    stage_sop_for_workspace(armature, staged)
    assert abs(load_sop(staged).operations[0].floating(SWING_RATE_PROPERTY) - 0.6) < 1e-6
    assert not (root / paths["unpack_sop"]).exists()

    state.minfo_path = ""
    state.edit_path = ""
    state.source_baseline_path = ""
    try:
        bpy.ops.gbfr.sop_save()
        raise AssertionError("source 主体不应允许单独导出 SOP")
    except RuntimeError as error:
        assert "请先导出一份当前主体" in str(error)
    assert not (root / paths["unpack_sop"]).exists()

    collection.gbfr_session.resolved_minfo_path = str(root / paths["unpack_minfo"])
    result = bpy.ops.gbfr.sop_save()
    assert result == {"FINISHED"}, result
    unpack_sop = root / paths["unpack_sop"]
    assert abs(load_sop(unpack_sop).operations[0].floating(SWING_RATE_PROPERTY) - 0.6) < 1e-6
    exported_bytes = unpack_sop.read_bytes()

    armature.gbfr_sop.operations[0].swing_rate = 0.7
    state.minfo_path = ""
    state.source_baseline_path = ""
    result = bpy.ops.gbfr.sop_restore_source("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    assert unpack_sop.read_bytes() == exported_bytes, "恢复 source 不应自动写文件"
    assert abs(armature.gbfr_sop.operations[0].swing_rate - 0.5) < 1e-6
    assert armature.gbfr_sop.dirty

    result = bpy.ops.gbfr.sop_save()
    assert result == {"FINISHED"}, result
    assert unpack_sop.read_bytes() == source_bytes

    saved_blend = root / "sop-driver-persistence.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(saved_blend)) == {"FINISHED"}
    assert bpy.ops.wm.open_mainfile(filepath=str(saved_blend)) == {"FINISHED"}
    reloaded_armature = bpy.data.objects["SOP Armature"]
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    reloaded_path = reloaded_armature.pose.bones["_a50"].path_from_id("rotation_quaternion")
    reloaded_drivers = [
        curve for curve in reloaded_armature.animation_data.drivers
        if curve.data_path == reloaded_path
        and curve.driver.expression.startswith(DRIVER_EXPRESSION_PREFIX)
    ]
    assert len(reloaded_drivers) == 4
    assert all(curve.driver.is_valid for curve in reloaded_drivers)

print("GBFR SOP edit/export/restore smoke test passed")
