"""Mode-aware Blender bone selection helpers."""

from __future__ import annotations


def _is_armature(armature) -> bool:
    return armature is not None and getattr(armature, "type", None) == "ARMATURE"


def _append_unique(items, seen_names, bone) -> None:
    name = getattr(bone, "name", None)
    if name and name not in seen_names:
        seen_names.add(name)
        items.append(bone)


def _belongs_to_armature(bone, armature) -> bool:
    owner = getattr(bone, "id_data", None)
    if owner is None or owner is armature or owner is armature.data:
        return True
    owner_pointer = getattr(owner, "as_pointer", None)
    if not callable(owner_pointer):
        return False
    for target in (armature, armature.data):
        target_pointer = getattr(target, "as_pointer", None)
        if callable(target_pointer) and owner_pointer() == target_pointer():
            return True
    return False


def _context_selected_bones(context, armature, bones, attributes) -> list:
    for attr in attributes:
        result = []
        seen_names = set()
        for candidate in getattr(context, attr, None) or []:
            if not _belongs_to_armature(candidate, armature):
                continue
            bone = bones.get(getattr(candidate, "name", ""))
            if bone is not None:
                _append_unique(result, seen_names, bone)
        if result:
            return result
    return []


def selected_edit_bones(context, armature) -> list:
    if not _is_armature(armature) or armature.mode != "EDIT":
        return []
    edit_bones = armature.data.edit_bones
    result = _context_selected_bones(
        context, armature, edit_bones,
        ("selected_editable_bones", "selected_bones"),
    )
    if result:
        return result
    seen_names = set()
    for bone in edit_bones:
        if (
            getattr(bone, "select", False)
            or getattr(bone, "select_head", False)
            or getattr(bone, "select_tail", False)
        ):
            _append_unique(result, seen_names, bone)
    return result


def _pose_bone_is_selected(pose_bone) -> bool:
    if hasattr(pose_bone, "select"):
        return bool(pose_bone.select)
    return bool(getattr(getattr(pose_bone, "bone", None), "select", False))


def selected_pose_bones(context, armature) -> list:
    if not _is_armature(armature) or armature.pose is None:
        return []
    pose_bones = armature.pose.bones
    result = _context_selected_bones(
        context, armature, pose_bones,
        ("selected_pose_bones_from_active_object", "selected_pose_bones"),
    )
    if result:
        return result
    seen_names = set()
    for bone in pose_bones:
        if _pose_bone_is_selected(bone):
            _append_unique(result, seen_names, bone)
    return result


def selected_bone_names(context, armature) -> list[str]:
    """Return selected names from Edit, Pose, or retained Object-mode state."""
    if not _is_armature(armature):
        return []
    if armature.mode == "EDIT":
        return [bone.name for bone in selected_edit_bones(context, armature)]
    names = [bone.name for bone in selected_pose_bones(context, armature)]
    if armature.mode == "POSE":
        return names
    seen_names = set(names)
    for bone in armature.data.bones:
        if getattr(bone, "select", False) and bone.name not in seen_names:
            seen_names.add(bone.name)
            names.append(bone.name)
    return names


__all__ = ["selected_bone_names", "selected_edit_bones", "selected_pose_bones"]
