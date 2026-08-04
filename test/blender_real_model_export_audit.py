"""Export selected roots from an opened blend and validate generated buffers.

Run with:
    blender file.blend --background --factory-startup --python this_file.py -- RootName [...]
"""

from pathlib import Path
import struct
import sys
import tempfile

import bpy


arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not arguments:
    raise SystemExit("Pass at least one armature root name after --")

bpy.ops.preferences.addon_enable(module="io_gbfr_blender_tools")

from io_gbfr_blender_tools.Entities.MInfo_ModelInfo.ModelInfo import ModelInfo
from io_gbfr_blender_tools.gbfr_model_export_v2 import write_some_data


def validate_model(minfo_path, output_root):
    model = ModelInfo.GetRootAs(bytearray(minfo_path.read_bytes()), 0)
    for lod_index in range(model.LodsLength()):
        lod = model.Lods(lod_index)
        mesh_path = output_root / f"lod{lod_index}" / f"{minfo_path.stem}.mmesh"
        data = mesh_path.read_bytes()
        assert lod.Buffers(0).Size() == lod.VertexCount() * 32
        index_buffer = lod.Buffers(lod.BuffersLength() - 1)
        assert index_buffer.Size() == lod.IndexCount() * 4
        indices = struct.unpack_from(f"<{lod.IndexCount()}I", data, index_buffer.Offset())
        assert max(indices, default=0) < lod.VertexCount()
        covered = []
        for chunk_index in range(lod.ChunksLength()):
            chunk = lod.Chunks(chunk_index)
            assert chunk.Offset() % 3 == 0 and chunk.Count() % 3 == 0
            assert chunk.Offset() + chunk.Count() <= lod.IndexCount()
            covered.extend(range(chunk.Offset(), chunk.Offset() + chunk.Count()))
        assert sorted(covered) == list(range(lod.IndexCount()))
        print(
            f"{minfo_path.stem} lod{lod_index}: vertices={lod.VertexCount()} "
            f"indices={lod.IndexCount()} chunks={lod.ChunksLength()}"
        )


with tempfile.TemporaryDirectory(prefix="gbfr_corner_export_") as temporary:
    output_root = Path(temporary)
    for root_name in arguments:
        root = bpy.data.objects[root_name]
        assert root.type == "ARMATURE"
        bpy.ops.object.select_all(action="DESELECT")
        root.select_set(True)
        bpy.context.view_layer.objects.active = root
        model_id = root_name.split(".", 1)[0]
        minfo_path = output_root / f"{model_id}.minfo"
        write_some_data(bpy.context, str(minfo_path), 1.0, False)
        validate_model(minfo_path, output_root)

print("GBFR real model corner export audit passed")
