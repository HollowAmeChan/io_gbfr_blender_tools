import math
import unittest

from gbfr_cloth_format import MISSING_BONE
from gbfr_cloth_tools import (
    SelectedBone, count_nonreciprocal_up_links, delete_nodes, generate_nodes, rebuild_nodes,
)


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

    def test_independent_chains_continue_through_longest_branch(self):
        selected = [
            SelectedBone("HairBack_01", 1),
            SelectedBone("HairBack_02", 2, "HairBack_01"),
            SelectedBone("HairBack_03", 3, "HairBack_02"),
            SelectedBone("HairBack_A_04", 4, "HairBack_03"),
            SelectedBone("HairBack_A_05", 5, "HairBack_A_04"),
            SelectedBone("HairBack_B_04", 6, "HairBack_03"),
            SelectedBone("HairBack_B_05", 7, "HairBack_B_04"),
            SelectedBone("HairBack_B_06", 8, "HairBack_B_05"),
        ]
        nodes, _preset, chains = generate_nodes(selected, "SKIRT", "CHAINS", False)
        self.assertEqual(
            [
                [
                    "HairBack_01", "HairBack_02", "HairBack_03",
                    "HairBack_B_04", "HairBack_B_05", "HairBack_B_06",
                ],
                ["HairBack_A_04", "HairBack_A_05"],
            ],
            [[bone.name for bone in chain] for chain in chains],
        )
        by_id = {node.bone: node for node in nodes}
        self.assertEqual(6, by_id[3].down)
        self.assertEqual(3, by_id[6].up)
        self.assertEqual(3, by_id[4].up)
        self.assertEqual(5, by_id[4].down)
        self.assertEqual(1, count_nonreciprocal_up_links(nodes))
        self.assertAlmostEqual(math.radians(90), by_id[8].rotation_limit)
        self.assertAlmostEqual(by_id[6].rotation_limit, by_id[4].rotation_limit)
        self.assertAlmostEqual(by_id[7].rotation_limit, by_id[5].rotation_limit)
        self.assertGreater(by_id[4].rotation_limit, by_id[1].rotation_limit)
        self.assertTrue(all(node.side == MISSING_BONE for node in nodes))
        self.assertTrue(all(node.poly == MISSING_BONE for node in nodes))
        rebuilt = {node.bone: node for node in rebuild_nodes(nodes, selected, "CHAINS", False)}
        self.assertEqual(6, rebuilt[3].down)
        self.assertEqual(3, rebuilt[6].up)
        self.assertEqual(3, rebuilt[4].up)
        self.assertNotEqual(4, rebuilt[3].down)

    def test_equal_length_forks_use_bone_name_as_tiebreaker(self):
        selected = [
            SelectedBone("Root", 1),
            SelectedBone("Branch_B", 2, "Root"),
            SelectedBone("Branch_A", 3, "Root"),
        ]
        nodes, _preset, chains = generate_nodes(selected, "LONG_HAIR", "CHAINS", False)
        self.assertEqual(
            [["Root", "Branch_A"], ["Branch_B"]],
            [[bone.name for bone in chain] for chain in chains],
        )
        by_id = {node.bone: node for node in nodes}
        self.assertEqual(3, by_id[1].down)
        self.assertEqual(1, by_id[2].up)
        self.assertEqual(1, by_id[3].up)
        self.assertEqual(1, count_nonreciprocal_up_links(nodes))

    def test_grid_rejects_branching_selection(self):
        selected = [
            SelectedBone("Root", 1),
            SelectedBone("ChildA", 2, "Root"),
            SelectedBone("ChildB", 3, "Root"),
        ]
        with self.assertRaisesRegex(ValueError, "分叉"):
            generate_nodes(selected, "SKIRT", "GRID", False)

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
