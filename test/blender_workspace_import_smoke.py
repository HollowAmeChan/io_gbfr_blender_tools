"""Run with: blender --background --python this_file.py -- path/to/model.minfo"""

from pathlib import Path
import sys

import bpy


try:
    separator = sys.argv.index("--")
    minfo = Path(sys.argv[separator + 1]).resolve()
except (ValueError, IndexError):
    raise SystemExit("Pass a workspace minfo after --")

bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")
result = bpy.ops.gbfr.import_mesh(filepath=str(minfo), import_scale=1.0)
assert result == {"FINISHED"}, result
armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
assert len(armatures) == 1, len(armatures)
state = armatures[0].gbfr_cloth
assert state.enabled
assert len(state.clp_groups) > 0
assert len(state.clh_layers) > 0
assert Path(state.workspace_path).name == "workspace.json"
assert any("gbfr_bone_id" in bone for bone in armatures[0].data.bones)
from io_gbfr_blender_tools import gbfr_cloth_blender
batches = []
gbfr_cloth_blender._draw_armature(armatures[0], batches)
assert sum(len(lines) for lines, _color, _width in batches) > 0
print(f"GBFR workspace import smoke passed: {len(state.clp_groups)} CLP / {len(state.clh_layers)} CLH")
