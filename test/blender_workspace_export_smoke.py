"""Run with: blender --background --python this_file.py -- path/to/model.minfo"""

from pathlib import Path
import json
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

from io_gbfr_blender_tools.gbfr_session import activate_session, session_collections
from io_gbfr_blender_tools.gbfr_workspace import resolve_model_bundle

bundle = resolve_model_bundle(minfo)
session = session_collections(bpy.context.scene)[0]
activate_session(bpy.context, session)
temporary_parent = bundle.workspace_root / ".gbfr"
temporary_parent.mkdir(parents=True, exist_ok=True)

with tempfile.TemporaryDirectory(prefix="export_smoke_", dir=temporary_parent) as temporary:
    root = Path(temporary)
    model_id = bundle.model_id
    model_type = model_id[:2]
    relative = {
        "minfo": Path(f"data/model/{model_type}/{model_id}/{model_id}.minfo"),
        "skeleton": Path(f"data/model/{model_type}/{model_id}/{model_id}.skeleton"),
        "mmesh": Path(f"data/model_streaming/lod0/{model_id}.mmesh"),
    }
    source_files = {
        "minfo": bundle.minfo,
        "skeleton": bundle.skeleton,
        "mmesh": bundle.mmesh,
    }
    records = []
    for file_type, relative_path in relative.items():
        source = root / "source" / relative_path
        unpack = root / "unpack" / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        unpack.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_files[file_type], source)
        shutil.copy2(source_files[file_type], unpack)
        records.append({
            "FileType": file_type,
            "Source": str(source.relative_to(root)),
            "Input": str(unpack.relative_to(root)),
            "Output": str(Path("build") / relative_path),
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
    for relative_path in relative.values():
        output = root / "unpack" / relative_path
        assert output.is_file() and output.stat().st_size > 0, output
    debug_json = root / ".gbfr" / "exports" / f"{model_id}.json"
    document = json.loads(debug_json.read_text(encoding="utf-8"))
    assert document["lods"][0]["vertex_count"] > 0
    assert Path(session.gbfr_session.workspace_path) == workspace_path
    assert Path(session.gbfr_session.resolved_minfo_path) == root / "unpack" / relative["minfo"]

print(f"GBFR workspace export smoke passed: {bundle.model_id}")
