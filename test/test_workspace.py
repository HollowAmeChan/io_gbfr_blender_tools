from pathlib import Path
import json
import tempfile
import unittest

from gbfr_workspace import WorkspaceError, find_workspace_json, resolve_model_bundle


class WorkspaceTests(unittest.TestCase):
    def test_resolves_streamed_mesh_and_cloth_from_minfo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                "minfo": "unpack/data/model/pl/pl9999/pl9999.minfo",
                "source_minfo": "source/data/model/pl/pl9999/pl9999.minfo",
                "skeleton": "unpack/data/model/pl/pl9999/pl9999.skeleton",
                "mmesh": "unpack/data/model_streaming/lod0/pl9999.mmesh",
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
            self.assertEqual([("clh", 1), ("clp", 0)], [(item.category, item.group_id) for item in bundle.cloth_files])
            self.assertEqual(workspace_path, find_workspace_json(root / paths["minfo"]))

    def test_rejects_unregistered_minfo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "workspace.json").write_text('{"Version": 1, "ModelFiles": []}', encoding="utf-8")
            selected = root / "unregistered.minfo"
            selected.write_bytes(b"fixture")
            with self.assertRaises(WorkspaceError):
                resolve_model_bundle(selected)


if __name__ == "__main__":
    unittest.main()
