from pathlib import Path
import json
import tempfile
import unittest

from gbfr_workspace import (
    WorkspaceError, find_workspace_json, resolve_model_bundle,
    resolve_model_export_targets,
)


class WorkspaceTests(unittest.TestCase):
    def test_resolves_streamed_mesh_and_cloth_from_minfo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                "minfo": "unpack/data/model/pl/pl9999/pl9999.minfo",
                "source_minfo": "source/data/model/pl/pl9999/pl9999.minfo",
                "sop": "source/data/model/pl/pl9999/pl9999.sop",
                "mot": "source/data/pl/pl9999/pl9999_0001.mot",
                "skeleton": "unpack/data/model/pl/pl9999/pl9999.skeleton",
                "mmesh": "unpack/data/model_streaming/lod0/pl9999.mmesh",
                "mmesh_lod1": "unpack/data/model_streaming/lod1/pl9999.mmesh",
                "mmesh_shadow": "unpack/data/model_streaming/shadowlod0/pl9999.mmesh",
                "material": "unpack/data/model/pl/pl9999/vars/0.mmat.json",
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
                    {"FileType": "skeleton", "Input": paths["skeleton"]},
                    {"FileType": "mmesh", "Input": paths["mmesh"]},
                    {"FileType": "mmesh", "Input": paths["mmesh_shadow"]},
                    {"FileType": "mmesh", "Input": paths["mmesh_lod1"]},
                ],
                "ClothFiles": [
                    {"Category": "clp", "GroupId": 0, "Xml": paths["clp"], "Source": "source/a.bxm", "Output": "build/a.bxm"},
                    {"Category": "clh", "GroupId": 1, "Xml": paths["clh"], "Source": "source/b.bxm", "Output": "build/b.bxm"},
                ],
            }
            workspace_path = root / "workspace.json"
            workspace_path.write_text(json.dumps(workspace), encoding="utf-8")
            bundle = resolve_model_bundle(root / paths["source_minfo"])
            self.assertEqual(root / paths["mmesh"], bundle.mmesh)
            self.assertEqual(tuple(root / paths[name] for name in ("mmesh", "mmesh_lod1", "mmesh_shadow")), bundle.mmeshes)
            self.assertEqual(root / paths["material"], bundle.material_json)
            self.assertEqual(root / paths["sop"], bundle.sop)
            self.assertEqual((root / paths["mot"],), bundle.animations)
            self.assertEqual([("clh", 1), ("clp", 0)], [(item.category, item.group_id) for item in bundle.cloth_files])
            self.assertEqual(workspace_path, find_workspace_json(root / paths["minfo"]))

            targets = resolve_model_export_targets(workspace_path, "pl9999")
            self.assertEqual(root / paths["minfo"], targets.minfo)
            self.assertEqual(root / paths["skeleton"], targets.skeleton)
            self.assertEqual(root / paths["mmesh"], targets.mmesh)
            self.assertEqual(tuple(root / paths[name] for name in ("mmesh", "mmesh_lod1", "mmesh_shadow")), targets.mmeshes)

    def test_rejects_unregistered_minfo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "workspace.json").write_text('{"Version": 1, "ModelFiles": []}', encoding="utf-8")
            selected = root / "unregistered.minfo"
            selected.write_bytes(b"fixture")
            with self.assertRaises(WorkspaceError):
                resolve_model_bundle(selected)

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
