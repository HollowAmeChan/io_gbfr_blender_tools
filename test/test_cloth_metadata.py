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


if __name__ == "__main__":
    unittest.main()
