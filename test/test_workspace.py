from pathlib import Path
import json
import tempfile
import unittest

from gbfr_workspace import (
    WorkspaceError, find_workspace_json, resolve_model_bundle,
    resolve_model_export_targets,
)
from gbfr_material import resolve_albedo_texture


class WorkspaceTests(unittest.TestCase):
    def test_resolves_streamed_mesh_and_cloth_from_minfo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                "minfo": "unpack/data/model/pl/pl9999/pl9999.minfo",
                "source_minfo": "source/data/model/pl/pl9999/pl9999.minfo",
                "sop": "source/data/model/pl/pl9999/pl9999.sop",
                "mot": "source/data/pl/pl9999/pl9999_0001.mot",
                "unpack_mot": "unpack/data/pl/pl9999/pl9999_0001.mot",
                "skeleton": "unpack/data/model/pl/pl9999/pl9999.skeleton",
                "source_skeleton": "source/data/model/pl/pl9999/pl9999.skeleton",
                "mmesh": "unpack/data/model_streaming/lod0/pl9999.mmesh",
                "mmesh_lod1": "unpack/data/model_streaming/lod1/pl9999.mmesh",
                "mmesh_shadow": "unpack/data/model_streaming/shadowlod0/pl9999.mmesh",
                "source_mmesh": "source/data/model_streaming/lod0/pl9999.mmesh",
                "source_mmesh_lod1": "source/data/model_streaming/lod1/pl9999.mmesh",
                "source_mmesh_shadow": "source/data/model_streaming/shadowlod0/pl9999.mmesh",
                "fp_minfo": "unpack/data/model/fp/fp9999/fp9999.minfo",
                "source_fp_minfo": "source/data/model/fp/fp9999/fp9999.minfo",
                "fp_mmesh": "unpack/data/model_streaming/lod0/fp9999.mmesh",
                "source_fp_mmesh": "source/data/model_streaming/lod0/fp9999.mmesh",
                "material": "unpack/data/model/pl/pl9999/vars/0.mmat.json",
                "source_texture": "source/data/granite/2k/pl9999_body.dds",
                "unpack_texture": "unpack/data/granite/2k/pl9999_body.dds",
                "clp": "unpack/data/pl/pl9999/cloth/pl9999_0_0_clp.bxm.xml",
                "clh": "unpack/data/pl/pl9999/cloth/pl9999_0_1_clh.bxm.xml",
            }
            for relative in paths.values():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            workspace = {
                "Version": 1, "CharacterId": "pl9999",
                "ModelFiles": [
                    {"FileType": "minfo", "Input": paths["minfo"], "Source": paths["source_minfo"]},
                    {"FileType": "skeleton", "Input": paths["skeleton"], "Source": paths["source_skeleton"]},
                    {"FileType": "mmesh", "Input": paths["mmesh"], "Source": paths["source_mmesh"]},
                    {"FileType": "mmesh", "Input": paths["mmesh_shadow"], "Source": paths["source_mmesh_shadow"]},
                    {"FileType": "mmesh", "Input": paths["mmesh_lod1"], "Source": paths["source_mmesh_lod1"]},
                    {"FileType": "minfo", "Input": paths["fp_minfo"], "Source": paths["source_fp_minfo"]},
                    {"FileType": "mmesh", "Input": paths["fp_mmesh"], "Source": paths["source_fp_mmesh"]},
                ],
                "AnimationFiles": [{
                    "ModelId": "pl9999", "FileType": "mot",
                    "Source": paths["mot"], "Input": paths["unpack_mot"],
                    "Output": "build/data/pl/pl9999/pl9999_0001.mot",
                    "SourceSha256": "source-hash", "BaselineSha256": "mot-hash",
                }],
                "ClothFiles": [
                    {"Category": "clp", "GroupId": 0, "Xml": paths["clp"], "Source": "source/a.bxm", "Output": "build/a.bxm", "SourceSha256": "source-hash", "BaselineSha256": "xml-hash"},
                    {"Category": "clh", "GroupId": 1, "Xml": paths["clh"], "Source": "source/b.bxm", "Output": "build/b.bxm"},
                ],
            }
            workspace_path = root / "workspace.json"
            workspace_path.write_text(json.dumps(workspace), encoding="utf-8")
            bundle = resolve_model_bundle(root / paths["source_minfo"])
            self.assertEqual(root / paths["source_minfo"], bundle.minfo)
            self.assertEqual(root / paths["source_skeleton"], bundle.skeleton)
            self.assertTrue(bundle.prefer_source)
            self.assertEqual((root / "source", root / "unpack"), bundle.texture_roots)
            self.assertEqual(root / paths["source_mmesh"], bundle.mmesh)
            self.assertEqual(tuple(root / paths[name] for name in ("source_mmesh", "source_mmesh_lod1", "source_mmesh_shadow")), bundle.mmeshes)
            self.assertEqual(root / paths["source_texture"], resolve_albedo_texture(bundle.texture_roots, "pl9999_body"))
            self.assertEqual(root / paths["material"], bundle.material_json)
            self.assertEqual(root / paths["sop"], bundle.sop)
            self.assertEqual(1, len(bundle.animations))
            animation = bundle.animations[0]
            self.assertEqual("pl9999_0001.mot", animation.name)
            self.assertEqual(root / paths["mot"], animation.source)
            self.assertEqual(root / paths["unpack_mot"], animation.unpack)
            self.assertEqual(root / paths["mot"], animation.preview)
            unpack_bundle = resolve_model_bundle(root / paths["minfo"])
            self.assertEqual(root / paths["unpack_mot"], unpack_bundle.animations[0].preview)
            self.assertEqual([("clh", 1), ("clp", 0)], [(item.category, item.group_id) for item in bundle.cloth_files])
            clp = next(item for item in bundle.cloth_files if item.category == "clp")
            self.assertEqual("source-hash", clp.source_sha256)
            self.assertEqual("xml-hash", clp.baseline_sha256)
            self.assertEqual(workspace_path, find_workspace_json(root / paths["minfo"]))

            face_bundle = resolve_model_bundle(root / paths["source_fp_minfo"])
            self.assertEqual("fp9999", face_bundle.model_id)
            self.assertEqual((), face_bundle.cloth_files)

            targets = resolve_model_export_targets(workspace_path, "pl9999")
            self.assertEqual(root / paths["minfo"], targets.minfo)
            self.assertEqual(root / paths["skeleton"], targets.skeleton)
            self.assertEqual(root / paths["source_skeleton"], targets.reference_skeleton)
            self.assertEqual(root / paths["mmesh"], targets.mmesh)
            self.assertEqual(tuple(root / paths[name] for name in ("mmesh", "mmesh_lod1", "mmesh_shadow")), targets.mmeshes)

            (root / paths["clp"]).unlink()
            with self.assertRaises(WorkspaceError):
                resolve_model_bundle(root / paths["minfo"])
            recovery_bundle = resolve_model_bundle(
                root / paths["minfo"], require_cloth_xml=False,
            )
            self.assertEqual(2, len(recovery_bundle.cloth_files))

    def test_rejects_cloth_record_with_conflicting_model_owners(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            minfo = root / "source/data/model/pl/pl9999/pl9999.minfo"
            mmesh = root / "source/data/model_streaming/lod0/pl9999.mmesh"
            minfo.parent.mkdir(parents=True)
            mmesh.parent.mkdir(parents=True)
            minfo.write_bytes(b"fixture")
            mmesh.write_bytes(b"fixture")
            workspace = {
                "Version": 1,
                "ModelFiles": [
                    {"FileType": "minfo", "Source": str(minfo.relative_to(root)), "Input": "unpack/pl9999.minfo"},
                    {"FileType": "mmesh", "Source": str(mmesh.relative_to(root)), "Input": "unpack/pl9999.mmesh"},
                ],
                "ClothFiles": [{
                    "Category": "clp", "GroupId": 0,
                    "Source": "source/data/pl/pl9999/cloth/pl9999_0_0_clp.bxm",
                    "Xml": "unpack/data/pl/pl8888/cloth/pl8888_0_0_clp.bxm.xml",
                    "Output": "build/data/pl/pl9999/cloth/pl9999_0_0_clp.bxm",
                }],
            }
            (root / "workspace.json").write_text(json.dumps(workspace), encoding="utf-8")
            with self.assertRaisesRegex(WorkspaceError, "属于不同模型"):
                resolve_model_bundle(minfo, require_cloth_xml=False)

    def test_rejects_unregistered_minfo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "workspace.json").write_text('{"Version": 1, "ModelFiles": []}', encoding="utf-8")
            selected = root / "unregistered.minfo"
            selected.write_bytes(b"fixture")
            with self.assertRaises(WorkspaceError):
                resolve_model_bundle(selected)

    def test_allows_unrigged_model_without_skeleton(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            minfo = root / "unpack/data/model/bg/bg9999/bg9999.minfo"
            source = root / "source/data/model/bg/bg9999/bg9999.minfo"
            mmesh = root / "unpack/data/model_streaming/lod0/bg9999.mmesh"
            for path in (minfo, source, mmesh):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            workspace_path = root / "workspace.json"
            workspace_path.write_text(json.dumps({
                "Version": 1,
                "ModelFiles": [
                    {"FileType": "minfo", "Input": str(minfo.relative_to(root)), "Source": str(source.relative_to(root))},
                    {"FileType": "mmesh", "Input": str(mmesh.relative_to(root))},
                ],
            }), encoding="utf-8")

            bundle = resolve_model_bundle(minfo)
            targets = resolve_model_export_targets(workspace_path, "bg9999")
            self.assertIsNone(bundle.skeleton)
            self.assertFalse(bundle.prefer_source)
            self.assertIsNone(targets.skeleton)
            self.assertIsNone(targets.reference_skeleton)

    def test_export_rejects_model_target_outside_unpack(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source/data/model/pl/pl9999/pl9999.minfo"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"fixture")
            workspace = {
                "Version": 1,
                "ModelFiles": [
                    {"FileType": "minfo", "Input": "outside/pl9999.minfo", "Source": str(source)},
                    {"FileType": "skeleton", "Input": "unpack/pl9999.skeleton"},
                    {"FileType": "mmesh", "Input": "unpack/pl9999.mmesh"},
                ],
            }
            workspace_path = root / "workspace.json"
            workspace_path.write_text(json.dumps(workspace), encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                resolve_model_export_targets(workspace_path, "pl9999")


if __name__ == "__main__":
    unittest.main()
