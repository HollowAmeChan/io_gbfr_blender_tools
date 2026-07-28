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
    def test_reads_current_material_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "0.mmat.json"
            path.write_text(json.dumps({"materials": [
                {
                    "shader_params": [{
                        "param_hash": "g_53F49792_EnableAlpha_GUESSED",
                        "value_or_offset": 1,
                    }],
                    "texture_maps": [{
                        "shader_map_name_hash": "g_AlbedoMap",
                        "texture_name": "pl9999_body_lod0_albd",
                    }],
                },
                {
                    "shader_params": [],
                    "texture_maps": [{
                        "shader_map_name_hash": "g_AlbedoMap",
                        "texture_name": "pl9999_body_lod0_c01_albd",
                    }],
                },
                {
                    "shader_params": [],
                    "texture_maps": [
                        {"shader_map_name_hash": "g_EyeWhiteTexture", "texture_name": "eye_base"},
                        {"shader_map_name_hash": "g_EyeIrisTexture", "texture_name": "eye_iris"},
                        {"shader_map_name_hash": "g_EyeHighLightTexture", "texture_name": "eye_highlight"},
                        {"shader_map_name_hash": "g_UnknownMap", "texture_name": "do_not_guess"},
                    ],
                },
            ]}), encoding="utf-8")
            definitions = load_material_definitions(path)
            self.assertEqual("pl9999_body_lod0_albd", definitions[0].albedo_name)
            self.assertTrue(definitions[0].alpha_enabled)
            self.assertIsNone(definitions[1].albedo_name)
            self.assertTrue(definitions[2].is_eye_material)
            self.assertTrue(is_color_variant_texture("pl9999_body_lod0_c01_albd"))

    def test_reads_legacy_material_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "0.mmat.json"
            path.write_text(json.dumps({"Entries1": [{
                "A1": [{"ID": ENABLE_ALPHA_PARAMETER_ID, "ID2": 1}],
                "A2": [{"ID": ALBEDO_TEXTURE_SLOT_ID, "Name": "legacy_albd"}],
            }]}), encoding="utf-8")
            definitions = load_material_definitions(path)
            self.assertEqual("legacy_albd", definitions[0].albedo_name)
            self.assertTrue(definitions[0].alpha_enabled)

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
