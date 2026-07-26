import unittest
from types import SimpleNamespace

from gbfr_bone_selection import selected_bone_names


class NamedCollection(list):
    def get(self, name, default=None):
        return next((value for value in self if value.name == name), default)


def bone(name, owner=None, **values):
    defaults = {
        "name": name,
        "id_data": owner,
        "select": False,
        "select_head": False,
        "select_tail": False,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


class BoneSelectionTests(unittest.TestCase):
    def test_edit_context_selection_does_not_merge_stale_flags(self):
        data = SimpleNamespace()
        edit_a = bone("A", data, select_head=True)
        edit_b = bone("B", data, select_tail=True)
        data.edit_bones = NamedCollection([edit_a, edit_b])
        data.bones = NamedCollection([])
        armature = SimpleNamespace(type="ARMATURE", mode="EDIT", data=data, pose=None)
        foreign = bone("Foreign", object(), select=True)
        context = SimpleNamespace(selected_editable_bones=[edit_a, foreign], selected_bones=[edit_b])
        self.assertEqual(["A"], selected_bone_names(context, armature))

    def test_edit_mode_falls_back_to_head_and_tail_selection(self):
        data = SimpleNamespace()
        edit_a = bone("A", data, select_head=True)
        edit_b = bone("B", data, select_tail=True)
        data.edit_bones = NamedCollection([edit_a, edit_b])
        data.bones = NamedCollection([])
        armature = SimpleNamespace(type="ARMATURE", mode="EDIT", data=data, pose=None)
        context = SimpleNamespace(selected_editable_bones=[], selected_bones=[])
        self.assertEqual(["A", "B"], selected_bone_names(context, armature))

    def test_pose_mode_supports_pose_bone_selection(self):
        data = SimpleNamespace()
        raw = bone("PoseSelected", data)
        data.bones = NamedCollection([raw])
        pose_bone = SimpleNamespace(name=raw.name, id_data=data, select=True, bone=raw)
        armature = SimpleNamespace(
            type="ARMATURE", mode="POSE", data=data,
            pose=SimpleNamespace(bones=NamedCollection([pose_bone])),
        )
        context = SimpleNamespace(selected_pose_bones_from_active_object=[], selected_pose_bones=[])
        self.assertEqual(["PoseSelected"], selected_bone_names(context, armature))

    def test_pose_context_selection_does_not_merge_stale_flags(self):
        data = SimpleNamespace()
        raw_a = bone("A", data)
        raw_b = bone("B", data, select=True)
        data.bones = NamedCollection([raw_a, raw_b])
        pose_a = SimpleNamespace(name="A", id_data=data, select=True, bone=raw_a)
        pose_b = SimpleNamespace(name="B", id_data=data, select=False, bone=raw_b)
        armature = SimpleNamespace(
            type="ARMATURE", mode="POSE", data=data,
            pose=SimpleNamespace(bones=NamedCollection([pose_a, pose_b])),
        )
        context = SimpleNamespace(selected_pose_bones_from_active_object=[pose_a], selected_pose_bones=[pose_b])
        self.assertEqual(["A"], selected_bone_names(context, armature))

    def test_object_mode_reads_retained_data_bone_selection_without_duplicates(self):
        data = SimpleNamespace()
        raw_a = bone("A", data, select=True)
        raw_b = bone("B", data, select=True)
        data.bones = NamedCollection([raw_a, raw_b])
        pose_a = SimpleNamespace(name="A", id_data=data, bone=raw_a)
        armature = SimpleNamespace(
            type="ARMATURE", mode="OBJECT", data=data,
            pose=SimpleNamespace(bones=NamedCollection([pose_a])),
        )
        context = SimpleNamespace(selected_pose_bones_from_active_object=[pose_a], selected_pose_bones=[])
        self.assertEqual(["A", "B"], selected_bone_names(context, armature))


if __name__ == "__main__":
    unittest.main()
