"""Run with: blender --background --factory-startup --python this_file.py"""

import json
from pathlib import Path
import tempfile

import bpy


bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")

from io_gbfr_blender_tools.gbfr_session import configure_session
from io_gbfr_blender_tools.gbfr_sop import (
    SOP_VERSION, SWING_RATE_PROPERTY, SopAsset, load_sop,
    make_swing_twist_operation, save_sop,
)
from io_gbfr_blender_tools.gbfr_sop_blender import (
    CONSTRAINT_PREFIX, populate_sop_state, stage_sop_for_workspace,
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
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, bone_id in (("_00e", 0x00E), ("_a50", 0xA50)):
        bone = armature.data.bones[name]
        bone["gbfr_bone_id"] = bone_id
        bone["gbfr_rest_quaternion"] = (1.0, 0.0, 0.0, 0.0)

    configure_session(
        collection, bundle, root / paths["source_minfo"],
        armature, armature, (), bpy.context.scene,
    )
    populate_sop_state(armature, bundle)
    state = armature.gbfr_sop
    assert state.enabled and len(state.operations) == 1
    assert not (root / paths["unpack_sop"]).exists()

    item = state.operations[0]
    item.swing_rate = 0.6
    constraints = [
        constraint for bone in armature.pose.bones for constraint in bone.constraints
        if constraint.name.startswith(CONSTRAINT_PREFIX)
    ]
    assert len(constraints) == 1
    assert abs(constraints[0].influence - 0.6) < 1e-6
    assert not (root / paths["unpack_sop"]).exists(), "Blender 内编辑不应自动写文件"

    staged = root / "staging/pl9999.sop"
    stage_sop_for_workspace(armature, staged)
    assert abs(load_sop(staged).operations[0].floating(SWING_RATE_PROPERTY) - 0.6) < 1e-6
    assert not (root / paths["unpack_sop"]).exists()

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
    result = bpy.ops.gbfr.sop_restore_source("EXEC_DEFAULT")
    assert result == {"FINISHED"}, result
    assert unpack_sop.read_bytes() == exported_bytes, "恢复 source 不应自动写文件"
    assert abs(armature.gbfr_sop.operations[0].swing_rate - 0.5) < 1e-6
    assert armature.gbfr_sop.dirty

    result = bpy.ops.gbfr.sop_save()
    assert result == {"FINISHED"}, result
    assert unpack_sop.read_bytes() == source_bytes

print("GBFR SOP edit/export/restore smoke test passed")
