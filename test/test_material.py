from pathlib import Path
import json
import tempfile
import unittest

from gbfr_material import (
    ALBEDO_TEXTURE_SLOT_ID,
    ENABLE_ALPHA_PARAMETER_ID,
    EYE_CONJUNCTIVA_TEXTURE_SLOT_ID,
    EYE_HIGHLIGHT_TEXTURE_SLOT_ID,
    EYE_IRIS_TEXTURE_SLOT_ID,
    is_color_variant_texture,
    load_material_definitions,
    resolve_albedo_texture,
)


class MaterialTests(unittest.TestCase):
    def test_reads_base_albedo_and_alpha_flag(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "0.mmat.json"
            path.write_text(json.dumps({"Entries1": [
                {
                    "A1": [{"ID": ENABLE_ALPHA_PARAMETER_ID, "ID2": 1}],
                    "A2": [{"ID": ALBEDO_TEXTURE_SLOT_ID, "Name": "pl9999_body_lod0_albd"}],
                },
                {
                    "A1": [],
                    "A2": [{"ID": ALBEDO_TEXTURE_SLOT_ID, "Name": "pl9999_body_lod0_c01_albd"}],
                },
                {
                    "A1": [],
                    "A2": [
                        {"ID": EYE_CONJUNCTIVA_TEXTURE_SLOT_ID, "Name": "eye_base"},
                        {"ID": EYE_IRIS_TEXTURE_SLOT_ID, "Name": "eye_iris"},
                        {"ID": EYE_HIGHLIGHT_TEXTURE_SLOT_ID, "Name": "eye_highlight"},
                    ],
                },
            ]}), encoding="utf-8")
            definitions = load_material_definitions(path)
            self.assertEqual("pl9999_body_lod0_albd", definitions[0].albedo_name)
            self.assertTrue(definitions[0].alpha_enabled)
            self.assertIsNone(definitions[1].albedo_name)
            self.assertTrue(definitions[2].is_eye_material)
            self.assertTrue(is_color_variant_texture("pl9999_body_lod0_c01_albd"))

    def test_resolves_granite_before_texture_and_plain_before_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            granite = root / "unpack/data/granite/2k/example.dds"
            texture = root / "unpack/data/texture/2k/example_0.dds"
            granite.parent.mkdir(parents=True)
            texture.parent.mkdir(parents=True)
            granite.write_bytes(b"granite")
            texture.write_bytes(b"texture")
            self.assertEqual(granite.resolve(), resolve_albedo_texture(root, "example"))


if __name__ == "__main__":
    unittest.main()
