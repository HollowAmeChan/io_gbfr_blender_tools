import math
import unittest

from gbfr_cloth_format import MISSING_BONE
from gbfr_cloth_tools import SelectedBone, delete_nodes, generate_nodes, rebuild_nodes


def chain(prefix, root_id, length):
    return [
        SelectedBone(
            name=f"{prefix}_{depth + 1:02d}",
            bone_id=root_id + depth,
            parent_name=f"{prefix}_{depth:02d}" if depth else None,
        )
        for depth in range(length)
    ]


class ClothToolTests(unittest.TestCase):
    def test_open_grid_uses_root_name_order_and_parent_depth(self):
        selected = chain("Skirt_B", 200, 3) + chain("Skirt_A", 100, 3)
        nodes, _preset, chains = generate_nodes(selected, "SKIRT", "GRID", False)
        self.assertEqual(["Skirt_A_01", "Skirt_B_01"], [value[0].name for value in chains])
        by_id = {node.bone: node for node in nodes}
        self.assertEqual(101, by_id[100].down)
        self.assertEqual(100, by_id[101].up)
        self.assertEqual(MISSING_BONE, by_id[100].side)
        self.assertEqual(100, by_id[200].side)
        self.assertEqual(by_id[200].side, by_id[200].poly)
        self.assertAlmostEqual(math.radians(10), by_id[100].rotation_limit)
        self.assertAlmostEqual(math.radians(90), by_id[102].rotation_limit)
        self.assertEqual(by_id[100].friction, by_id[200].friction)

    def test_closed_grid_connects_first_root_to_last(self):
        selected = chain("C", 300, 2) + chain("A", 100, 2) + chain("B", 200, 2)
        nodes, _preset, _chains = generate_nodes(selected, "SKIRT", "GRID", True)
        by_id = {node.bone: node for node in nodes}
        self.assertEqual(300, by_id[100].side)
        self.assertEqual(100, by_id[200].side)
        self.assertEqual(200, by_id[300].side)

    def test_branching_selection_is_rejected(self):
        selected = [
            SelectedBone("Root", 1),
            SelectedBone("ChildA", 2, "Root"),
            SelectedBone("ChildB", 3, "Root"),
        ]
        with self.assertRaisesRegex(ValueError, "分叉"):
            generate_nodes(selected, "LONG_HAIR")

    def test_delete_only_clears_references_to_removed_nodes(self):
        selected = chain("A", 100, 3) + chain("B", 200, 3)
        nodes, _preset, _chains = generate_nodes(selected, "SKIRT", "GRID", False)
        survivors, removed, cleared = delete_nodes(nodes, {101})
        by_id = {node.bone: node for node in survivors}
        self.assertEqual(1, removed)
        self.assertEqual(4, cleared)
        self.assertEqual(MISSING_BONE, by_id[100].down)
        self.assertEqual(MISSING_BONE, by_id[102].up)
        self.assertEqual(100, by_id[200].side)
        self.assertEqual(MISSING_BONE, by_id[201].side)
        self.assertEqual(MISSING_BONE, by_id[201].poly)

    def test_rebuild_preserves_parameters(self):
        selected = chain("B", 200, 3) + chain("A", 100, 3)
        nodes, _preset, _chains = generate_nodes(selected, "SKIRT", "CHAINS", False)
        nodes[0].weight = 42.0
        rebuilt = rebuild_nodes(nodes, selected, "GRID", False)
        by_id = {node.bone: node for node in rebuilt}
        self.assertEqual(42.0, by_id[100].weight)
        self.assertEqual(100, by_id[200].side)


if __name__ == "__main__":
    unittest.main()
