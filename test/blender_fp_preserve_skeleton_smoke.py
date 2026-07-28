"""Run with: blender --background --python this_file.py -- path/to/fp.minfo"""

from pathlib import Path
import json
import shutil
import sys
import tempfile

import bpy
from mathutils import Vector


separator = sys.argv.index("--")
minfo = Path(sys.argv[separator + 1]).resolve()
skeleton = minfo.with_suffix(".skeleton")

bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
assert bpy.ops.gbfr.import_mesh(filepath=str(minfo), import_scale=1.0) == {"FINISHED"}

from io_gbfr_blender_tools.Entities.ModelSkeleton import ModelSkeleton
from io_gbfr_blender_tools.gbfr_export import _validate_skeleton_contract
from io_gbfr_blender_tools.gbfr_cloth_blender import clp_numeric_name_reference_groups
from io_gbfr_blender_tools.gbfr_model_export_v2 import build_skeleton, ordered_export_bones
from io_gbfr_blender_tools.gbfr_session import active_session_collection, active_session_root
from io_gbfr_blender_tools.gbfr_workspace import resolve_model_bundle

root = active_session_root(bpy.context)
assert root is not None and root.type == "ARMATURE"
assert not root.gbfr_cloth.enabled
assert len(root.gbfr_cloth.clp_groups) == 0
assert len(root.gbfr_cloth.clh_layers) == 0
assert clp_numeric_name_reference_groups(root) == {}
# The source contains this non-deform dummy, but Blender drops its near-zero
# scale while applying the imported rest pose.
assert root.data.bones.get("_8d0") is None
source_bytes = skeleton.read_bytes()
source_skeleton = ModelSkeleton.GetRootAs(bytearray(source_bytes), 0)
source_names = [
    source_skeleton.Body(index).Name()
    for index in range(source_skeleton.BodyLength())
]
probe_index = source_names.index(b"_830")
missing_index = source_names.index(b"_8d0")

# Move a real face bone's rest position. The merged export must use this
# Blender transform while retaining the source-only _8d0 slot.
bpy.context.view_layer.objects.active = root
root.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
probe_edit_bone = root.data.edit_bones["_830"]
offset = Vector((0.0123, -0.0045, 0.0067))
probe_edit_bone.head += offset
probe_edit_bone.tail += offset
bpy.ops.object.mode_set(mode="OBJECT")

_validate_skeleton_contract(
    root, skeleton, preserve_missing_reference_bones=True,
)
export_bones = ordered_export_bones(
    root, source_skeleton, preserve_missing_reference_bones=True,
)
assert len(export_bones) == source_skeleton.BodyLength()
assert export_bones[missing_index] is None
probe_bone = root.data.bones["_830"]
probe_local = probe_bone.parent.matrix_local.inverted() @ probe_bone.matrix_local
merged_bytes, _deform_table = build_skeleton(
    root, export_bones=export_bones, reference_skeleton=source_skeleton,
)
merged = ModelSkeleton.GetRootAs(bytearray(merged_bytes), 0)
merged_position = merged.Body(probe_index).Position()
assert (
    Vector((merged_position.X(), merged_position.Y(), merged_position.Z()))
    - probe_local.translation
).length < 1e-6
source_position = source_skeleton.Body(probe_index).Position()
assert (
    Vector((merged_position.X(), merged_position.Y(), merged_position.Z()))
    - Vector((source_position.X(), source_position.Y(), source_position.Z()))
).length > 1e-6

def bone_values(bone):
    return (
        bone.ParentId(),
        bone.Name(),
        (bone.Position().X(), bone.Position().Y(), bone.Position().Z()),
        (bone.Quat().X(), bone.Quat().Y(), bone.Quat().Z(), bone.Quat().W()),
        (bone.Scale().X(), bone.Scale().Y(), bone.Scale().Z()),
        None if bone.A1() is None else (bone.A1().BoneId(), bone.A1().Unk()),
    )

assert bone_values(merged.Body(missing_index)) == bone_values(
    source_skeleton.Body(missing_index)
)

bundle = resolve_model_bundle(minfo)
session = active_session_collection(bpy.context)
with tempfile.TemporaryDirectory(prefix="gbfr_fp_workspace_") as temporary:
    workspace_root = Path(temporary)
    records = []
    assets = [
        ("minfo", bundle.minfo, Path("data/model/fp/fp1400/fp1400.minfo")),
        ("skeleton", bundle.skeleton, Path("data/model/fp/fp1400/fp1400.skeleton")),
        *(
            ("mmesh", path, Path(f"data/model_streaming/{path.parent.name}/fp1400.mmesh"))
            for path in bundle.mmeshes
        ),
    ]
    for file_type, source_path, relative in assets:
        source_copy = workspace_root / "source" / relative
        unpack_copy = workspace_root / "unpack" / relative
        source_copy.parent.mkdir(parents=True, exist_ok=True)
        unpack_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, source_copy)
        shutil.copy2(source_path, unpack_copy)
        records.append({
            "FileType": file_type,
            "Source": source_copy.relative_to(workspace_root).as_posix(),
            "Input": unpack_copy.relative_to(workspace_root).as_posix(),
        })
    workspace = workspace_root / "workspace.json"
    workspace.write_text(json.dumps({
        "Version": 1,
        "CharacterId": "pl1400",
        "ModelFiles": records,
        "ClothFiles": [],
    }), encoding="utf-8")
    assert bpy.ops.gbfr.export_mesh(filepath=str(workspace)) == {"FINISHED"}
    assert "0 个 Cloth XML" in session.gbfr_session.last_status
    exported_skeleton = workspace_root / records[1]["Input"]
    exported = ModelSkeleton.GetRootAs(bytearray(exported_skeleton.read_bytes()), 0)
    assert exported_skeleton.read_bytes() != source_bytes
    assert exported.BodyLength() == source_skeleton.BodyLength()
    assert [exported.Body(index).Name() for index in range(exported.BodyLength())] == source_names
    assert [
        exported.Body(index).ParentId()
        for index in range(exported.BodyLength())
    ] == [
        source_skeleton.Body(index).ParentId()
        for index in range(source_skeleton.BodyLength())
    ]
    assert bone_values(exported.Body(missing_index)) == bone_values(
        source_skeleton.Body(missing_index)
    )
    exported_position = exported.Body(probe_index).Position()
    assert (
        Vector((exported_position.X(), exported_position.Y(), exported_position.Z()))
        - Vector((source_position.X(), source_position.Y(), source_position.Z()))
    ).length > 1e-6

print("GBFR FP edited rest skeleton merge smoke passed")
