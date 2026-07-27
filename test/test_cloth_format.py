from pathlib import Path
import hashlib
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from gbfr_cloth_format import (
    ClhCollision, ClpNode, load_clh, load_clp,
    restore_cloth_xml_from_source, write_clh, write_clp,
)


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

    @staticmethod
    def sha256(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

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

    def test_restores_complete_cloth_set_from_source_before_installing(self):
        tool = self.root / "GBFRDataTools.exe"
        tool.write_bytes(b"fixture tool")
        records = []
        fixtures = {
            "clp": FIXTURES / "sample_clp.bxm.xml",
            "clh": FIXTURES / "sample_clh.bxm.xml",
        }
        for category, baseline in fixtures.items():
            source = self.root / f"sample_{category}.bxm"
            source.write_bytes(f"source {category}".encode("ascii"))
            destination = self.root / "unpack" / baseline.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("edited", encoding="utf-8")
            records.append(SimpleNamespace(
                category=category,
                source=source,
                xml=destination,
                source_sha256=self.sha256(source),
                baseline_sha256=self.sha256(baseline),
            ))

        def decode(command, **_kwargs):
            source = Path(command[command.index("-i") + 1])
            output = Path(command[command.index("-o") + 1])
            category = "clp" if "clp" in source.name else "clh"
            shutil.copy2(fixtures[category], output)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("gbfr_cloth_format.subprocess.run", side_effect=decode) as runner:
            count = restore_cloth_xml_from_source(records, self.root, tool)

        self.assertEqual(2, count)
        self.assertEqual(2, runner.call_count)
        for record in records:
            self.assertEqual(
                fixtures[record.category].read_bytes(), Path(record.xml).read_bytes(),
            )

    def test_restore_rejects_bad_baseline_without_touching_unpack(self):
        tool = self.root / "GBFRDataTools.exe"
        tool.write_bytes(b"fixture tool")
        source = self.root / "sample_clp.bxm"
        source.write_bytes(b"source clp")
        destination = self.root / "sample_clp.bxm.xml"
        destination.write_bytes(b"keep current unpack")
        record = SimpleNamespace(
            category="clp",
            source=source,
            xml=destination,
            source_sha256=self.sha256(source),
            baseline_sha256="0" * 64,
        )

        def decode(command, **_kwargs):
            output = Path(command[command.index("-o") + 1])
            shutil.copy2(FIXTURES / "sample_clp.bxm.xml", output)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("gbfr_cloth_format.subprocess.run", side_effect=decode):
            with self.assertRaisesRegex(ValueError, "基线不一致"):
                restore_cloth_xml_from_source((record,), self.root, tool)
        self.assertEqual(b"keep current unpack", destination.read_bytes())


if __name__ == "__main__":
    unittest.main()
