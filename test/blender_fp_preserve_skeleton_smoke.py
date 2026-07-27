"""Run with: blender --background --python this_file.py -- path/to/fp.minfo"""

from pathlib import Path
import json
import shutil
import sys
import tempfile

import bpy


separator = sys.argv.index("--")
minfo = Path(sys.argv[separator + 1]).resolve()
skeleton = minfo.with_suffix(".skeleton")

bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
assert bpy.ops.gbfr.import_mesh(filepath=str(minfo), import_scale=1.0) == {"FINISHED"}

from io_gbfr_blender_tools.Entities.ModelSkeleton import ModelSkeleton
from io_gbfr_blender_tools.gbfr_export import _validate_skeleton_contract
from io_gbfr_blender_tools.gbfr_cloth_blender import clp_numeric_name_reference_groups
from io_gbfr_blender_tools.gbfr_model_export_v2 import write_some_data
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
_validate_skeleton_contract(root, skeleton, preserve_reference_skeleton=True)

with tempfile.TemporaryDirectory(prefix="gbfr_fp_preserve_") as temporary:
    output = Path(temporary) / "fp1400.minfo"
    write_some_data(
        bpy.context,
        str(output),
        1.0,
        True,
        reference_skeleton_path=str(skeleton),
        preserve_reference_skeleton=True,
    )
    exported = Path(temporary) / "model/fp/fp1400/fp1400.skeleton"
    assert exported.read_bytes() == skeleton.read_bytes()
    parsed = ModelSkeleton.GetRootAs(bytearray(exported.read_bytes()), 0)
    assert parsed.BodyLength() == 103
    assert parsed.Body(102).Name() == b"_8d0"

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
    for file_type, source, relative in assets:
        source_copy = workspace_root / "source" / relative
        unpack_copy = workspace_root / "unpack" / relative
        source_copy.parent.mkdir(parents=True, exist_ok=True)
        unpack_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, source_copy)
        shutil.copy2(source, unpack_copy)
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

print("GBFR FP reference skeleton preservation smoke passed")
