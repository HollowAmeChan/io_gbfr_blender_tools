"""Pure CLP creation and topology helpers used by the Blender operators."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Iterable

try:
    from .gbfr_cloth_format import ClpNode, MISSING_BONE
except ImportError:  # Direct module import used by the non-Blender unit tests.
    from gbfr_cloth_format import ClpNode, MISSING_BONE


@dataclass(frozen=True)
class SelectedBone:
    name: str
    bone_id: int
    parent_name: str | None = None


@dataclass(frozen=True)
class ClpPreset:
    key: str
    label: str
    topology: str
    header: dict[str, int | float | tuple[float, float, float, float]]
    curves: dict[str, tuple[tuple[float, float], ...]]
    offset: tuple[float, float, float, float] = (0.1, 0.0, 0.0, 1.0)
    joint_scale: float = 1.0
    allow_change_scale: bool = False
    axis_adjust_rate: float = 1.0


def _curve(points: Iterable[tuple[float, float]], position: float) -> float:
    points = tuple(points)
    if not points:
        return 0.0
    if position <= points[0][0]:
        return points[0][1]
    if position >= points[-1][0]:
        return points[-1][1]
    for (left_t, left_value), (right_t, right_value) in zip(points, points[1:]):
        if position <= right_t:
            span = right_t - left_t
            ratio = 0.0 if span <= 0.0 else (position - left_t) / span
            return left_value + (right_value - left_value) * ratio
    return points[-1][1]


def _depth_curve(values: Iterable[float]) -> tuple[tuple[float, float], ...]:
    values = tuple(values)
    if len(values) == 1:
        return ((0.0, values[0]),)
    denominator = len(values) - 1
    return tuple((index / denominator, value) for index, value in enumerate(values))


def _header(**values):
    return values


_SKIRT = ClpPreset(
    "SKIRT", "裙摆", "GRID",
    _header(
        airResistance_=0.65, windResistance_=0.76, stretchy_=0.1,
        stretchyHInner_=0.1, stretchyWOuter_=0.1, stretchyWInner_=1.0,
        gravityVec_=(0.0, -0.001, 0.0, 1.0), localGravityType_=2,
        localGravityRate_=0.07, localGravityBlendRate_=0.85,
        originalRate_=0.0, bHitFloorEnable_=1, bWorldWindEnable_=1,
        moveSpdRate_=0.5,
    ),
    {
        "rotation_limit": _depth_curve(map(math.radians, (10, 15, 40, 90, 90, 90))),
        "friction": _depth_curve((0.9, 0.9, 0.9, 0.3, 0.3, 0.3)),
        "gravity_blend_rate": _depth_curve((0.0, 0.0, 0.9, 0.95, 0.95, 0.98)),
        "original_rate": _depth_curve((0.005, 0.005, 0.001, 0.0, 0.0, 0.0)),
        "weight": _depth_curve((6.0, 6.3, 6.6, 6.9, 7.6, 8.0)),
        "thickness": _depth_curve((0.005, 0.01, 0.015, 0.025, 0.03, 0.035)),
        "wind_area": _depth_curve((-0.04, -0.04, -0.04, -0.02, -0.02, -0.01)),
    },
)

_SHAPED_CLOTH = ClpPreset(
    "SHAPED_CLOTH", "定型布片 / 袖子", "GRID",
    _header(
        airResistance_=0.6, windResistance_=0.5, stretchy_=0.5,
        stretchyHInner_=0.1, stretchyWOuter_=0.5, stretchyWInner_=1.0,
        gravityVec_=(0.0, -0.001, 0.0, 1.0), localGravityType_=2,
        localGravityRate_=0.01, localGravityBlendRate_=0.5,
        originalRate_=0.05, bHitFloorEnable_=0, bWorldWindEnable_=1,
        moveSpdRate_=0.5,
    ),
    {
        "rotation_limit": _depth_curve(map(math.radians, (10, 60, 60))),
        "friction": _depth_curve((0.9, 0.9, 0.9)),
        "gravity_blend_rate": _depth_curve((0.0, 0.0, 0.0)),
        "original_rate": _depth_curve((0.1, 0.1, 0.125)),
        "weight": _depth_curve((1.0, 1.0, 1.0)),
        "thickness": _depth_curve((0.003, 0.003, 0.004)),
        "wind_area": _depth_curve((0.0, 0.0, 0.0)),
    },
)

_LONG_HAIR = ClpPreset(
    "LONG_HAIR", "长发", "CHAINS",
    _header(
        airResistance_=0.77, windResistance_=0.77, stretchy_=0.2,
        stretchyHInner_=0.0, stretchyWOuter_=0.2, stretchyWInner_=1.0,
        gravityVec_=(0.0, -0.001, 0.0, 1.0), localGravityType_=2,
        localGravityRate_=0.05, localGravityBlendRate_=0.6,
        originalRate_=0.0, bHitFloorEnable_=1, bWorldWindEnable_=1,
        moveSpdRate_=0.59,
    ),
    {
        "rotation_limit": _depth_curve(map(math.radians, (45, 30, 50, 180, 180, 180))),
        "friction": _depth_curve((0.9, 0.9, 0.9, 0.9, 0.9, 0.9)),
        "gravity_blend_rate": _depth_curve((0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        "original_rate": _depth_curve((0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        "weight": _depth_curve((1.5, 1.5, 1.5, 1.5, 1.2, 1.5)),
        "thickness": _depth_curve((0.0, 0.02, 0.032, 0.032, 0.032, 0.032)),
        "wind_area": _depth_curve((0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
    },
)

_SHORT_HAIR = ClpPreset(
    "SHORT_HAIR", "短发", "CHAINS",
    _header(
        airResistance_=0.95, windResistance_=0.25, stretchy_=0.2,
        stretchyHInner_=0.0, stretchyWOuter_=0.2, stretchyWInner_=1.0,
        gravityVec_=(0.0, -0.001, 0.0, 1.0), localGravityType_=0,
        localGravityRate_=0.01, localGravityBlendRate_=0.5,
        originalRate_=0.4, bHitFloorEnable_=0, bWorldWindEnable_=1,
        moveSpdRate_=0.5,
    ),
    {
        "rotation_limit": _depth_curve(map(math.radians, (7, 7, 7))),
        "friction": _depth_curve((0.9, 0.9, 0.9)),
        "gravity_blend_rate": _depth_curve((0.0, 0.0, 0.0)),
        "original_rate": _depth_curve((0.0, 0.0, 0.0)),
        "weight": _depth_curve((2.0, 2.0, 2.0)),
        "thickness": _depth_curve((0.0, 0.01, 0.015)),
        "wind_area": _depth_curve((0.01, 0.01, 0.01)),
    },
)

_BRAID = ClpPreset(
    "BRAID", "辫子", "CHAINS",
    _header(
        airResistance_=0.8, windResistance_=0.8, stretchy_=0.2,
        stretchyHInner_=0.0, stretchyWOuter_=0.2, stretchyWInner_=0.1,
        gravityVec_=(0.0, -0.002, 0.0, 1.0), localGravityType_=2,
        localGravityRate_=0.05, localGravityBlendRate_=0.95,
        originalRate_=0.0, bHitFloorEnable_=1, bWorldWindEnable_=1,
        moveSpdRate_=0.5,
    ),
    {
        "rotation_limit": _depth_curve(map(math.radians, (10, 25, 40, 50, 60, 70, 80, 90))),
        "friction": _depth_curve((0.9,) * 8),
        "gravity_blend_rate": _depth_curve((0.0,) * 8),
        "original_rate": _depth_curve((0.0, 0.0, 0.008, 0.006, 0.004, 0.002, 0.0, 0.0)),
        "weight": _depth_curve((3.0, 1.8, 1.8, 1.8, 1.5, 1.2, 1.0, 1.0)),
        "thickness": _depth_curve((0.0, 0.02, 0.025, 0.025, 0.02, 0.025, 0.03, 0.03)),
        "wind_area": _depth_curve((0.0, -0.005, -0.01, -0.01, 0.0, 0.0, 0.002, 0.02)),
    },
)

_ROPE = ClpPreset(
    "ROPE", "绳索 / 刀鞘", "CHAINS",
    _header(
        airResistance_=0.7, windResistance_=0.74, stretchy_=0.2,
        stretchyHInner_=1.0, stretchyWOuter_=0.2, stretchyWInner_=1.0,
        gravityVec_=(0.0, -0.003, 0.0, 1.0), localGravityType_=2,
        localGravityRate_=0.01, localGravityBlendRate_=0.55,
        originalRate_=0.001, bHitFloorEnable_=1, bWorldWindEnable_=1,
        moveSpdRate_=0.5,
    ),
    {
        "rotation_limit": _depth_curve((math.pi / 2.0,) * 10),
        "friction": _depth_curve((0.95,) * 10),
        "gravity_blend_rate": _depth_curve((0.5, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 1.0, 1.0)),
        "original_rate": _depth_curve((0.0,) * 10),
        "weight": _depth_curve((1.8, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0)),
        "thickness": _depth_curve((0.001,) + (0.01,) * 9),
        "wind_area": _depth_curve((0.041, 0.0355, 0.032, 0.0355, 0.032, 0.032, 0.032, 0.032, 0.032, 0.032)),
    },
)


PRESETS = (_SKIRT, _SHAPED_CLOTH, _LONG_HAIR, _SHORT_HAIR, _BRAID, _ROPE)
PRESET_BY_KEY = {preset.key: preset for preset in PRESETS}


def preset(key: str) -> ClpPreset:
    try:
        return PRESET_BY_KEY[key]
    except KeyError as error:
        raise ValueError(f"未知 CLP 预设: {key}") from error


def build_chains(selected: Iterable[SelectedBone], allow_branches: bool = False) -> list[list[SelectedBone]]:
    values = list(selected)
    if not values:
        raise ValueError("请先选择至少一根骨骼")
    by_name: dict[str, SelectedBone] = {}
    by_id: dict[int, SelectedBone] = {}
    for value in values:
        if value.name in by_name:
            raise ValueError(f"选择中存在重复骨名: {value.name}")
        if int(value.bone_id) in by_id:
            raise ValueError(f"选择中存在重复导出骨号: {value.bone_id}")
        by_name[value.name] = value
        by_id[int(value.bone_id)] = value
    children: dict[str, list[SelectedBone]] = {name: [] for name in by_name}
    roots = []
    for value in values:
        if value.parent_name in by_name:
            children[value.parent_name].append(value)
        else:
            roots.append(value)
    if not roots:
        raise ValueError("所选骨骼没有 root；请检查父子关系是否形成循环")
    chains: list[list[SelectedBone]] = []
    visited: set[str] = set()
    path_lengths: dict[str, int] = {}

    def longest_path_length(value: SelectedBone) -> int:
        cached = path_lengths.get(value.name)
        if cached is not None:
            return cached
        value_children = children[value.name]
        length = 1 + max((longest_path_length(child) for child in value_children), default=0)
        path_lengths[value.name] = length
        return length

    def append_segment(start: SelectedBone) -> None:
        chain: list[SelectedBone] = []
        deferred_branches: list[SelectedBone] = []
        current: SelectedBone | None = start
        while current is not None:
            if current.name in visited:
                raise ValueError(f"骨骼层级存在循环或重复路径: {current.name}")
            visited.add(current.name)
            chain.append(current)
            current_children = sorted(children[current.name], key=lambda item: item.name)
            if len(current_children) <= 1:
                current = current_children[0] if current_children else None
                continue
            names = ", ".join(child.name for child in current_children)
            if not allow_branches:
                raise ValueError(f"骨链 {current.name} 出现分叉: {names}")
            continuation = sorted(
                current_children,
                key=lambda child: (-longest_path_length(child), child.name),
            )[0]
            deferred_branches.extend(child for child in current_children if child is not continuation)
            current = continuation
        chains.append(chain)
        for child in deferred_branches:
            append_segment(child)

    for root in sorted(roots, key=lambda item: item.name):
        append_segment(root)
    if len(visited) != len(values):
        missing = sorted(set(by_name) - visited)
        raise ValueError(f"无法从 root 解析所选骨链: {', '.join(missing[:8])}")
    return chains


def _topology_links(chains: list[list[SelectedBone]], topology: str, closed: bool) -> dict[int, dict[str, int]]:
    links = {
        bone.bone_id: {"up": MISSING_BONE, "down": MISSING_BONE, "side": MISSING_BONE, "poly": MISSING_BONE}
        for chain in chains for bone in chain
    }
    for chain in chains:
        for current, following in zip(chain, chain[1:]):
            links[current.bone_id]["down"] = following.bone_id
            links[following.bone_id]["up"] = current.bone_id
    if topology != "GRID" or len(chains) < 2:
        return links
    for chain_index in range(1, len(chains)):
        left = chains[chain_index - 1]
        right = chains[chain_index]
        for depth in range(min(len(left), len(right))):
            links[right[depth].bone_id]["side"] = left[depth].bone_id
            links[right[depth].bone_id]["poly"] = left[depth].bone_id
    if closed and len(chains) > 2:
        first, last = chains[0], chains[-1]
        for depth in range(min(len(first), len(last))):
            links[first[depth].bone_id]["side"] = last[depth].bone_id
            links[first[depth].bone_id]["poly"] = last[depth].bone_id
    return links


def generate_nodes(selected: Iterable[SelectedBone], preset_key: str, topology: str | None = None, closed: bool = False) -> tuple[list[ClpNode], ClpPreset, list[list[SelectedBone]]]:
    chosen_preset = preset(preset_key)
    topology = topology or chosen_preset.topology
    if topology not in {"CHAINS", "GRID"}:
        raise ValueError(f"未知 CLP 拓扑模式: {topology}")
    chains = build_chains(selected, allow_branches=topology == "CHAINS")
    links = _topology_links(chains, topology, closed)
    max_depth = max(len(chain) for chain in chains) - 1
    nodes: list[ClpNode] = []
    for chain in chains:
        for depth, bone in enumerate(chain):
            position = 0.0 if max_depth <= 0 else depth / max_depth
            values = {
                field: _curve(chosen_preset.curves[field], position)
                for field in (
                    "rotation_limit", "friction", "gravity_blend_rate", "original_rate",
                    "weight", "thickness", "wind_area",
                )
            }
            link = links[bone.bone_id]
            nodes.append(ClpNode(
                data_version=2, bone=bone.bone_id,
                up=link["up"], down=link["down"], side=link["side"], poly=link["poly"],
                fix=MISSING_BONE, offset=chosen_preset.offset,
                joint_scale=chosen_preset.joint_scale,
                allow_change_scale=chosen_preset.allow_change_scale,
                axis_adjust_rate=chosen_preset.axis_adjust_rate,
                **values,
            ))
    return nodes, chosen_preset, chains


def delete_nodes(nodes: Iterable[ClpNode], bone_ids: Iterable[int]) -> tuple[list[ClpNode], int, int]:
    values = list(nodes)
    removed = {int(value) for value in bone_ids}
    survivors = [replace(node) for node in values if node.bone not in removed]
    removed_count = len(values) - len(survivors)
    cleared = 0
    for node in survivors:
        for field in ("up", "down", "side", "poly", "fix"):
            if getattr(node, field) in removed:
                setattr(node, field, MISSING_BONE)
                cleared += 1
    return survivors, removed_count, cleared


def rebuild_nodes(nodes: Iterable[ClpNode], bones: Iterable[SelectedBone], topology: str, closed: bool) -> list[ClpNode]:
    values = list(nodes)
    by_id = {node.bone: node for node in values}
    selected = [bone for bone in bones if bone.bone_id in by_id]
    chains = build_chains(selected, allow_branches=topology == "CHAINS")
    links = _topology_links(chains, topology, closed)
    result: list[ClpNode] = []
    for chain in chains:
        for bone in chain:
            node = replace(by_id[bone.bone_id])
            link = links[bone.bone_id]
            node.up, node.down = link["up"], link["down"]
            node.side, node.poly = link["side"], link["poly"]
            result.append(node)
    return result
