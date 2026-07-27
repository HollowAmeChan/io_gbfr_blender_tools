import unittest

from bone_name_mappings import (
    BONE_NAME_MAPPINGS, FACE_DEFORM_GROUPS, FACE_SEMANTIC_ALIASES,
)


class BoneNameMappingTests(unittest.TestCase):
    def test_face_deform_primary_names_are_unique_and_mirror_compatible(self):
        primary_names = []
        mapped_ids = set()
        for index, group in enumerate(FACE_DEFORM_GROUPS):
            base = f"FaceDeform{index:02d}"
            mapped_ids.update(group)
            if len(group) == 1:
                primary = BONE_NAME_MAPPINGS[group[0]][0]
                self.assertIn(base, BONE_NAME_MAPPINGS[group[0]])
                self.assertFalse(primary.endswith((".L", ".R")))
                primary_names.append(primary)
            else:
                left, right = group
                left_primary = BONE_NAME_MAPPINGS[left][0]
                right_primary = BONE_NAME_MAPPINGS[right][0]
                self.assertIn(base + ".L", BONE_NAME_MAPPINGS[left])
                self.assertIn(base + ".R", BONE_NAME_MAPPINGS[right])
                self.assertTrue(left_primary.endswith(".L"))
                self.assertEqual(left_primary[:-2] + ".R", right_primary)
                primary_names.extend((left_primary, right_primary))
        self.assertEqual(len(primary_names), len(set(primary_names)))
        self.assertTrue(all(name.startswith("_8") for name in mapped_ids))

    def test_existing_semantic_aliases_remain_available_for_reverse_conversion(self):
        self.assertIn("Eye_L", BONE_NAME_MAPPINGS["_8a0"])
        self.assertIn("Eye_R", BONE_NAME_MAPPINGS["_8a1"])
        self.assertIn("Brow_01_L", BONE_NAME_MAPPINGS["_830"])
        self.assertIn("Brow_01_R", BONE_NAME_MAPPINGS["_838"])

    def test_confirmed_semantic_names_are_primary(self):
        for bone_name, semantic_name in FACE_SEMANTIC_ALIASES.items():
            self.assertEqual(semantic_name, BONE_NAME_MAPPINGS[bone_name][0])
        self.assertEqual("BrowInner.L", BONE_NAME_MAPPINGS["_830"][0])
        self.assertEqual("UpperEyelid.L", BONE_NAME_MAPPINGS["_837"][0])
        self.assertEqual("EyeBall.L", BONE_NAME_MAPPINGS["_8a0"][0])
        self.assertEqual("UpperTeeth", BONE_NAME_MAPPINGS["_8b0"][0])
        self.assertEqual("LowerTeeth", BONE_NAME_MAPPINGS["_8b5"][0])
        self.assertEqual("TongueTip", BONE_NAME_MAPPINGS["_8c2"][0])


if __name__ == "__main__":
    unittest.main()
