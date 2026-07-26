from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

from gbfr_cloth_format import ClhCollision, ClpNode, load_clh, load_clp, write_clh, write_clp


FIXTURES = Path(__file__).parent / "fixtures"


class ClothFormatTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self, name):
        destination = self.root / name
        shutil.copy2(FIXTURES / name, destination)
        return destination

    def test_clp_round_trip_preserves_unknown_xml(self):
        path = self.fixture("sample_clp.bxm.xml")
        document = load_clp(path)
        self.assertEqual(18, document.header["useCollisionFlags_"])
        self.assertEqual([11, 12], [node.bone for node in document.nodes])
        document.header["airResistance_"] = 0.77
        document.nodes[0].thickness = 0.125
        write_clp(document)
        root = ET.parse(path).getroot()
        self.assertEqual("keep", root.attrib["fixture"])
        self.assertEqual("preserve me", root.findtext("./CLOTH_HEADER/futureHeader"))
        self.assertEqual("keep", root.findtext("./CLOTH_WK_LIST/CLOTH_WK/futureNode"))
        self.assertEqual("0.770000", root.findtext("./CLOTH_HEADER/airResistance_"))
        self.assertEqual("0.125000", root.findtext("./CLOTH_WK_LIST/CLOTH_WK/thick_"))

    def test_clh_can_edit_remove_and_add_without_losing_unknown_fields(self):
        path = self.fixture("sample_clh.bxm.xml")
        document = load_clh(path)
        document.collisions[0].radius = 0.09
        document.collisions.pop(1)
        document.collisions.append(ClhCollision(collision_id=5, p1=13, p2=13, radius=0.02, capsule=0))
        write_clh(document)
        root = ET.parse(path).getroot()
        values = root.findall("./ClothCollision_LIST/ClothCollision")
        self.assertEqual("2", root.findtext("CLOTH_AT_NUM"))
        self.assertEqual(["0", "5"], [item.findtext("id_") for item in values])
        self.assertEqual("keep", values[0].findtext("futureCollision"))
        self.assertEqual("0.090000", values[0].findtext("radius"))

    def test_clp_can_remove_and_add_topology_nodes(self):
        path = self.fixture("sample_clp.bxm.xml")
        document = load_clp(path)
        document.nodes = [document.nodes[1], ClpNode(bone=99, up=12, weight=3.5)]
        write_clp(document)
        root = ET.parse(path).getroot()
        values = root.findall("./CLOTH_WK_LIST/CLOTH_WK")
        self.assertEqual("2", root.findtext("CLOTH_WK_NUM"))
        self.assertEqual(["12", "99"], [item.findtext("no") for item in values])
        self.assertEqual("12", values[1].findtext("noUp"))
        self.assertEqual("3.500000", values[1].findtext("weight_"))

        document = load_clp(path)
        document.nodes.clear()
        write_clp(document)
        root = ET.parse(path).getroot()
        self.assertEqual("0", root.findtext("CLOTH_WK_NUM"))
        self.assertEqual([], root.findall("./CLOTH_WK_LIST/CLOTH_WK"))


if __name__ == "__main__":
    unittest.main()
