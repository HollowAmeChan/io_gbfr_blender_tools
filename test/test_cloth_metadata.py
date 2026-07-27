import unittest

from gbfr_cloth_format import CLP_HEADER_FLOATS, CLP_HEADER_INTS
from gbfr_cloth_metadata import CLP_HEADER_GROUPS, CLP_HEADER_UI


class ClothMetadataTests(unittest.TestCase):
    def test_every_known_header_has_a_readable_name_and_section(self):
        fields = set(CLP_HEADER_FLOATS + CLP_HEADER_INTS)
        self.assertEqual(fields, set(CLP_HEADER_UI))
        for label, description in CLP_HEADER_UI.values():
            self.assertTrue(label)
            self.assertTrue(description)

        grouped = {name for _title, names in CLP_HEADER_GROUPS for name in names}
        separately_drawn = {"dataVersion_", "id_", "useCollisionFlags_"}
        self.assertEqual(fields, grouped | separately_drawn)

    def test_group_preset_experience_is_kept_in_field_descriptions(self):
        former_preset_fields = {
            "airResistance_", "windResistance_", "stretchy_", "stretchyHInner_",
            "stretchyWOuter_", "stretchyWInner_", "originalRate_",
            "localGravityRate_", "localGravityBlendRate_", "moveSpdRate_",
            "bWorldWindEnable_", "localGravityType_", "bHitFloorEnable_",
        }
        for name in former_preset_fields:
            self.assertIn("经验参考", CLP_HEADER_UI[name][1], name)


if __name__ == "__main__":
    unittest.main()
