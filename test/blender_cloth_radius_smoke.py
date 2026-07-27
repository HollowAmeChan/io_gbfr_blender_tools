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
armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
state = armature.gbfr_cloth
assert state.enabled and any(node.thickness > 0.0 for group in state.clp_groups for node in group.nodes)

from io_gbfr_blender_tools import gbfr_cloth_blender

state.show_topology = False
state.show_collisions = False
state.show_node_radius = True
batches = []
gbfr_cloth_blender._draw_armature(armature, batches)
visible_batches = [batch for batch in batches if batch[0]]
assert len(visible_batches) == 1
lines, color, _width = visible_batches[0]
assert lines and color == (0.65, 0.28, 1.0, 0.82)

state.show_node_radius = False
batches = []
gbfr_cloth_blender._draw_armature(armature, batches)
assert not any(lines for lines, _color, _width in batches)
print(f"GBFR cloth radius smoke passed: {len(lines)} line vertices, color={color}")
