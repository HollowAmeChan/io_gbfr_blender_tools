"""Run with: blender --background --python this_file.py -- path/to/model.minfo"""

import json
from pathlib import Path
import shutil
import struct
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
from io_gbfr_blender_tools.Entities.MInfo_ModelInfo.VertexBufferType import VertexBufferType
from io_gbfr_blender_tools.Entities.ModelSkeleton import ModelSkeleton
from io_gbfr_blender_tools.gbfr_cloth_format import load_clp
from io_gbfr_blender_tools.gbfr_model_export_v2 import (
    KNOWN_FP_FACE_BONE_NAMES,
    export_bone_name,
    _allocate_appended_bone_names,
    quantize_vertex_weights,
)
from io_gbfr_blender_tools.gbfr_session import activate_session, session_collections
from io_gbfr_blender_tools.gbfr_workspace import resolve_model_bundle

assert _allocate_appended_bone_names(set(), set(), 2) == ["_c00", "_c01"]
occupied_append_names = {f"_{index:03d}" for index in range(1000)}
assert _allocate_appended_bone_names(
    {"_a79"}, occupied_append_names, 2
) == ["_c00", "_c01"]
letter_names = {
    *(f"_c{value:02x}" for value in range(0x100)),
    *(f"_a{value:02x}" for value in range(0x100)),
    *(f"_d{value:02x}" for value in range(0x100)),
}
numeric_before_face = {f"_{value:03d}" for value in range(830)}
assert _allocate_appended_bone_names(
    set(), letter_names | numeric_before_face, 1,
) == ["_834"]
assert {"_830", "_880", "_890"} <= KNOWN_FP_FACE_BONE_NAMES
assert quantize_vertex_weights([1.0]) == (65535,)
assert quantize_vertex_weights([0.5, 0.3, 0.2]) == (32768, 19660, 13107)
assert quantize_vertex_weights([2.0, 1.0]) == (43690, 21845)
assert sum(quantize_vertex_weights([0.137, 0.219, 0.271, 0.373])) == 65535
try:
    quantize_vertex_weights([])
except ValueError:
    pass
else:
    raise AssertionError("Empty vertex weights must be rejected")

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
weighted_mesh = next(
	mesh
	for lod in session_root.children
	for mesh in lod.children
	if mesh.type == "MESH" and len(mesh.data.vertices) > 0
)
extra_group = weighted_mesh.vertex_groups.new(name=extra_bone_name)
extra_group.add([0], 1.0, "REPLACE")

# Blender appends .001 when a replacement object retains the source mesh name.
# Both objects must map to the same global MeshInfo entry, not a local child index.
duplicate_mesh = weighted_mesh.copy()
duplicate_mesh.data = weighted_mesh.data.copy()
duplicate_mesh.name = f"{weighted_mesh.name.split('.')[0]}.001"
weighted_mesh.users_collection[0].objects.link(duplicate_mesh)
duplicate_mesh.parent = weighted_mesh.parent
assert duplicate_mesh.name.split('.')[0] == weighted_mesh.name.split('.')[0]
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

    cloth_records = []
    for record in bundle.cloth_files:
        xml_relative = record.xml.relative_to(bundle.workspace_root)
        target_xml = root / xml_relative
        target_xml.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record.xml, target_xml)
        cloth_records.append({
            "Source": record.source.relative_to(bundle.workspace_root).as_posix(),
            "Xml": xml_relative.as_posix(),
            "Output": record.output.relative_to(bundle.workspace_root).as_posix(),
            "Category": record.category,
            "GroupId": record.group_id,
        })

    cloth_state = session_root.gbfr_cloth
    test_group = next(group for group in cloth_state.clp_groups if group.nodes)
    test_node = next(node for node in test_group.nodes if node.bone_ref)
    opaque_group = next((
        group for group in cloth_state.clp_groups
        if any(not node.bone_ref for node in group.nodes)
    ), None)
    opaque_signature = None
    if opaque_group is not None:
        opaque_node = next(node for node in opaque_group.nodes if not node.bone_ref)
        opaque_signature = (
            int(opaque_node.bone), int(opaque_node.up), int(opaque_node.down),
            int(opaque_node.side), int(opaque_node.poly), int(opaque_node.fix),
        )
    test_node.friction += 0.123456
    expected_friction = test_node.friction
    expected_export_name = export_bone_name(session_root.data.bones[test_node.bone_ref])
    expected_bone_id = int(expected_export_name[1:], 16)
    stale_id = next(
        value for value in range(4094, 0, -1)
        if value != expected_bone_id
        and all(value != node.bone for group in cloth_state.clp_groups for node in group.nodes)
    )
    test_node.bone = stale_id

    workspace_path = root / "workspace.json"
    workspace_path.write_text(json.dumps({
        "Version": 1,
        "CharacterId": model_id,
        "UnpackRoot": "unpack",
        "ModelFiles": records,
        "ClothFiles": cloth_records,
    }), encoding="utf-8")

    result = bpy.ops.gbfr.export_mesh(
        filepath=str(workspace_path),
        export_scale=1.0,
        experimental_rename_new_bones=True,
    )
    assert result == {"FINISHED"}, (result, session.gbfr_session.last_status)
    outputs = [root / "unpack" / relative_path for _kind, _source, relative_path in files]
    assert all(path.is_file() and path.stat().st_size > 0 for path in outputs), outputs
    target_clp_record = next(
        record for record in cloth_records
        if record["Category"] == "clp" and record["GroupId"] == test_group.group_id
    )
    exported_clp = load_clp(root / target_clp_record["Xml"])
    exported_test_node = next(node for node in exported_clp.nodes if node.bone == expected_bone_id)
    assert abs(exported_test_node.friction - expected_friction) < 1e-6
    assert any(
        node.bone == expected_bone_id and node.bone_ref
        for node in test_group.nodes
    )
    if opaque_group is not None:
        opaque_clp_record = next(
            record for record in cloth_records
            if record["Category"] == "clp" and record["GroupId"] == opaque_group.group_id
        )
        exported_opaque_clp = load_clp(root / opaque_clp_record["Xml"])
        assert any(
            (node.bone, node.up, node.down, node.side, node.poly, node.fix) == opaque_signature
            for node in exported_opaque_clp.nodes
        )
    assert not (root / target_clp_record["Output"]).exists()
    assert f"{len(cloth_records)} 个 Cloth XML" in session.gbfr_session.last_status

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
    appended_name = exported_skeleton.Body(original_bone_count).Name().decode("utf-8")
    assert len(appended_name) == 4 and appended_name[1] in "cad"
    assert appended_name not in KNOWN_FP_FACE_BONE_NAMES
    assert exported_skeleton.Body(original_bone_count).ParentId() == 6
    assert session_root.data.bones.get(extra_bone_name) is not None
    assert weighted_mesh.vertex_groups.get(extra_bone_name) is not None
    regular_lods = [path for path in outputs if path.suffix == ".mmesh" and path.parent.name.startswith("lod")]
    shadow_lods = [path for path in outputs if path.suffix == ".mmesh" and path.parent.name.startswith("shadowlod")]
    assert model_info.LodsLength() == len(regular_lods)
    assert model_info.ShadowLodsLength() == len(shadow_lods)
    for lod_index in range(model_info.LodsLength()):
        lod = model_info.Lods(lod_index)
        for chunk_index in range(lod.ChunksLength()):
            assert lod.Chunks(chunk_index).MeshId() < model_info.MeshesLength()
    for index, output in enumerate(sorted(regular_lods, key=lambda path: path.parent.name)):
        lod = model_info.Lods(index)
        final_buffer = lod.Buffers(lod.BuffersLength() - 1)
        assert output.stat().st_size == final_buffer.Offset() + final_buffer.Size()
        flags = [
            name
            for name, value in VertexBufferType.__dict__.items()
            if not name.startswith("__")
            and isinstance(value, int)
            and lod.BufferTypes() & value
        ]
        weight_labels = ["BLENDWEIGHT"]
        if "BLENDWEIGHT_2" in flags:
            weight_labels.append("BLENDWEIGHT_2")
        vertex_weight_sums = [0] * lod.VertexCount()
        output_bytes = output.read_bytes()
        for label in weight_labels:
            locator = lod.Buffers(flags.index(label))
            assert locator.Size() == lod.VertexCount() * 8
            values = struct.iter_unpack(
                "<HHHH",
                output_bytes[locator.Offset():locator.Offset() + locator.Size()],
            )
            for vertex_index, row in enumerate(values):
                vertex_weight_sums[vertex_index] += sum(row)
        assert set(vertex_weight_sums) == {65535}, (
            output,
            min(vertex_weight_sums),
            max(vertex_weight_sums),
        )
    lod_signatures = {
        (
            model_info.Lods(index).VertexCount(),
            model_info.Lods(index).IndexCount(),
            model_info.Lods(index).ChunksLength(),
            model_info.Lods(index).BufferTypes(),
        )
        for index in range(model_info.LodsLength())
    }
    assert len(lod_signatures) == 1, lod_signatures

    assert Path(session.gbfr_session.workspace_path) == workspace_path
    assert Path(session.gbfr_session.resolved_minfo_path) == minfo_output

print(f"GBFR v2 workspace export smoke passed: {bundle.model_id} ({len(bundle.mmeshes)} LOD files)")
