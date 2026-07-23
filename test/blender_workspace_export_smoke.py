"""Run with: blender --background --python this_file.py -- path/to/model.minfo"""

import json
from pathlib import Path
import shutil
import sys
import tempfile

import bpy


try:
    separator = sys.argv.index("--")
    minfo = Path(sys.argv[separator + 1]).resolve()
except (ValueError, IndexError):
    raise SystemExit("Pass a workspace minfo after --")

bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
assert bpy.ops.gbfr.import_mesh(filepath=str(minfo), import_scale=1.0) == {"FINISHED"}

from io_gbfr_blender_tools.Entities.MInfo_ModelInfo.ModelInfo import ModelInfo
from io_gbfr_blender_tools.Entities.ModelSkeleton import ModelSkeleton
from io_gbfr_blender_tools.gbfr_session import activate_session, session_collections
from io_gbfr_blender_tools.gbfr_workspace import resolve_model_bundle

bundle = resolve_model_bundle(minfo)
session = session_collections(bpy.context.scene)[0]
activate_session(bpy.context, session)
temporary_parent = bundle.workspace_root / ".gbfr"
temporary_parent.mkdir(parents=True, exist_ok=True)

# Typical mod workflow only edits LOD0. Lower regular LODs are intentionally removed.
session_root = session.gbfr_session.root
source_skeleton = ModelSkeleton.GetRootAs(bytearray(bundle.skeleton.read_bytes()), 0)
original_bone_count = source_skeleton.BodyLength()
bpy.context.view_layer.objects.active = session_root
bpy.ops.object.mode_set(mode="EDIT")
extra_bone = session_root.data.edit_bones.new("GBFR_ORDER_TEST_EXTRA")
extra_bone.head = (0.0, 0.0, 0.0)
extra_bone.tail = (0.0, 0.05, 0.0)
extra_bone.parent = session_root.data.edit_bones[6]
extra_bone_name = extra_bone.name
bpy.ops.object.mode_set(mode="OBJECT")
assert session_root.data.bones.find(extra_bone_name) < original_bone_count
removed_regular_lods = []
for lod_object in list(session_root.children):
    name = lod_object.name.casefold()
    if not any(f"lod{index}" in name for index in range(1, 5)) or "shadowlod" in name:
        continue
    removed_regular_lods.append(name)
    for child in list(lod_object.children):
        bpy.data.objects.remove(child, do_unlink=True)
    bpy.data.objects.remove(lod_object, do_unlink=True)
assert removed_regular_lods

with tempfile.TemporaryDirectory(prefix="export_smoke_", dir=temporary_parent) as temporary:
    root = Path(temporary)
    model_id = bundle.model_id
    model_type = model_id[:2]
    files = [
        ("minfo", bundle.minfo, Path(f"data/model/{model_type}/{model_id}/{model_id}.minfo")),
        ("skeleton", bundle.skeleton, Path(f"data/model/{model_type}/{model_id}/{model_id}.skeleton")),
    ]
    for mmesh in bundle.mmeshes:
        files.append(("mmesh", mmesh, Path(f"data/model_streaming/{mmesh.parent.name}/{model_id}.mmesh")))

    records = []
    for file_type, source_file, relative_path in files:
        source = root / "source" / relative_path
        unpack = root / "unpack" / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        unpack.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, source)
        shutil.copy2(source_file, unpack)
        records.append({
            "FileType": file_type,
            "Source": source.relative_to(root).as_posix(),
            "Input": unpack.relative_to(root).as_posix(),
            "Output": (Path("build") / relative_path).as_posix(),
        })

    workspace_path = root / "workspace.json"
    workspace_path.write_text(json.dumps({
        "Version": 1,
        "CharacterId": model_id,
        "UnpackRoot": "unpack",
        "ModelFiles": records,
    }), encoding="utf-8")

    result = bpy.ops.gbfr.export_mesh(filepath=str(workspace_path), export_scale=1.0)
    assert result == {"FINISHED"}, (result, session.gbfr_session.last_status)
    outputs = [root / "unpack" / relative_path for _kind, _source, relative_path in files]
    assert all(path.is_file() and path.stat().st_size > 0 for path in outputs), outputs

    minfo_output = root / "unpack" / files[0][2]
    model_info = ModelInfo.GetRootAs(bytearray(minfo_output.read_bytes()), 0)
    skeleton_output = root / "unpack" / files[1][2]
    exported_skeleton = ModelSkeleton.GetRootAs(bytearray(skeleton_output.read_bytes()), 0)
    assert exported_skeleton.BodyLength() == original_bone_count + 1
    for index in range(original_bone_count):
        source_bone = source_skeleton.Body(index)
        exported_bone = exported_skeleton.Body(index)
        assert exported_bone.Name() == source_bone.Name(), index
        assert exported_bone.ParentId() == source_bone.ParentId(), index
    assert exported_skeleton.Body(original_bone_count).Name() == b"GBFR_ORDER_TEST_EXTRA"
    assert exported_skeleton.Body(original_bone_count).ParentId() == 6
    regular_lods = [path for path in outputs if path.suffix == ".mmesh" and path.parent.name.startswith("lod")]
    shadow_lods = [path for path in outputs if path.suffix == ".mmesh" and path.parent.name.startswith("shadowlod")]
    assert model_info.LodsLength() == len(regular_lods)
    assert model_info.ShadowLodsLength() == len(shadow_lods)
    for index, output in enumerate(sorted(regular_lods, key=lambda path: path.parent.name)):
        lod = model_info.Lods(index)
        final_buffer = lod.Buffers(lod.BuffersLength() - 1)
        assert output.stat().st_size == final_buffer.Offset() + final_buffer.Size()
    assert len({output.read_bytes() for output in regular_lods}) == 1

    assert Path(session.gbfr_session.workspace_path) == workspace_path
    assert Path(session.gbfr_session.resolved_minfo_path) == minfo_output

print(f"GBFR v2 workspace export smoke passed: {bundle.model_id} ({len(bundle.mmeshes)} LOD files)")
