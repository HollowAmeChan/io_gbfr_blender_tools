import unittest

from bone_name_mappings import BONE_NAME_MAPPINGS, FACE_DEFORM_GROUPS


class BoneNameMappingTests(unittest.TestCase):
    def test_face_deform_primary_names_are_unique_and_mirror_compatible(self):
        primary_names = []
        mapped_ids = set()
        for index, group in enumerate(FACE_DEFORM_GROUPS):
            base = f"FaceDeform{index:02d}"
            mapped_ids.update(group)
            if len(group) == 1:
                self.assertEqual(base, BONE_NAME_MAPPINGS[group[0]][0])
                primary_names.append(base)
            else:
                left, right = group
                self.assertEqual(base + ".L", BONE_NAME_MAPPINGS[left][0])
                self.assertEqual(base + ".R", BONE_NAME_MAPPINGS[right][0])
                primary_names.extend((base + ".L", base + ".R"))
        self.assertEqual(len(primary_names), len(set(primary_names)))
        self.assertTrue(all(name.startswith("_8") for name in mapped_ids))

    def test_existing_semantic_aliases_remain_available_for_reverse_conversion(self):
        self.assertIn("Eye_L", BONE_NAME_MAPPINGS["_8a0"])
        self.assertIn("Eye_R", BONE_NAME_MAPPINGS["_8a1"])
        self.assertIn("Brow_01_L", BONE_NAME_MAPPINGS["_830"])
        self.assertIn("Brow_01_R", BONE_NAME_MAPPINGS["_838"])


if __name__ == "__main__":
    unittest.main()
