"""Run with: blender --background --python this_file.py -- path/to/fp.minfo"""

from pathlib import Path
import sys
import tempfile

import bpy


separator = sys.argv.index("--")
minfo = Path(sys.argv[separator + 1]).resolve()
skeleton = minfo.with_suffix(".skeleton")

bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
assert bpy.ops.gbfr.import_mesh(filepath=str(minfo), import_scale=1.0) == {"FINISHED"}

from io_gbfr_blender_tools.Entities.ModelSkeleton import ModelSkeleton
from io_gbfr_blender_tools.gbfr_model_export_v2 import write_some_data
from io_gbfr_blender_tools.gbfr_session import active_session_root

root = active_session_root(bpy.context)
assert root is not None and root.type == "ARMATURE"
# The source contains this non-deform dummy, but Blender drops its near-zero
# scale while applying the imported rest pose.
assert root.data.bones.get("_8d0") is None

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

print("GBFR FP reference skeleton preservation smoke passed")
