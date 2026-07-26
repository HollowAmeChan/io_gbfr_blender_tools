"""Lossless-in-structure CLP/CLH XML editing.

Known fields are updated in an existing tree. Unknown elements and attributes remain
untouched so newly discovered game fields survive a Blender round trip.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET


MISSING_BONE = 4095

CLP_HEADER_FLOATS = (
    "reboundRate_", "airResistance_", "windResistance_", "stretchy_",
    "stretchyHInner_", "stretchyWOuter_", "stretchyWInner_", "hitAdjustRate_",
    "originalRate_", "simulationRate4CS_", "localGravityRate_",
    "localGravityBlendRate_", "teleportResetDis_", "floorHeight_",
    "windRateFromBack_", "moveSpdRate_", "shortHairadjust_",
    "airResistance4Chest_", "localGravityRate4Chest_",
)
CLP_HEADER_INTS = (
    "dataVersion_", "id_", "collisionLevels_", "childTraceLevels_",
    "gravityPartsNo_", "bParentGravity_", "fixAxis_", "bNoStretchy_",
    "bWorldWindEnable_", "bAtCenter_", "atDensity_", "localGravityType_",
    "localGravityBlendFlg_", "bLateAddMode_", "bNotReCalc_",
    "bHitFloorEnable_", "bBlendRateLast_", "useCollisionFlags_",
    "bIsUseWindPowUp_", "bChestParamAvailable_",
)


@dataclass
class ClpNode:
    data_version: int = 2
    bone: int = 0
    up: int = MISSING_BONE
    down: int = MISSING_BONE
    side: int = MISSING_BONE
    poly: int = MISSING_BONE
    fix: int = MISSING_BONE
    rotation_limit: float = 0.0
    friction: float = 0.0
    gravity_blend_rate: float = 0.0
    offset: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    original_rate: float = 0.0
    weight: float = 1.0
    thickness: float = 0.0
    wind_area: float = 0.0
    joint_scale: float = 1.0
    allow_change_scale: bool = False
    axis_adjust_rate: float = 1.0


@dataclass
class ClpDocument:
    path: Path
    header: dict[str, int | float | tuple[float, float, float, float]] = field(default_factory=dict)
    nodes: list[ClpNode] = field(default_factory=list)


@dataclass
class ClhCollision:
    data_version: int = 1
    collision_id: int = 0
    p1: int = 0
    p2: int = 0
    weight: float = 0.0
    radius: float = 0.01
    offset1: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    offset2: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    capsule: int = -1
    disabled_in_battle: bool = False
    disabled_in_idle: bool = False


@dataclass
class ClhDocument:
    path: Path
    collisions: list[ClhCollision] = field(default_factory=list)


def _tree(path: str | Path, root_name: str) -> ET.ElementTree:
    try:
        tree = ET.parse(path, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    except (OSError, ET.ParseError) as error:
        raise ValueError(f"无法解析 {Path(path).name}: {error}") from error
    if tree.getroot().tag != root_name:
        raise ValueError(f"{Path(path).name} 根节点应为 {root_name}")
    return tree


def _text(parent: ET.Element, name: str, default: str = "") -> str:
    node = parent.find(name)
    return node.text.strip() if node is not None and node.text else default


def _int(parent: ET.Element, name: str, default: int = 0) -> int:
    return int(_text(parent, name, str(default)), 0)


def _float(parent: ET.Element, name: str, default: float = 0.0) -> float:
    return float(_text(parent, name, str(default)))


def _vec4(parent: ET.Element, name: str, default=(0.0, 0.0, 0.0, 0.0)) -> tuple[float, float, float, float]:
    values = tuple(float(value) for value in _text(parent, name, " ".join(map(str, default))).split())
    if len(values) != 4:
        raise ValueError(f"{name} 应包含四个浮点数")
    return values


def load_clp(path: str | Path) -> ClpDocument:
    path = Path(path)
    root = _tree(path, "CLOTH").getroot()
    header_node = root.find("CLOTH_HEADER")
    list_node = root.find("CLOTH_WK_LIST")
    if header_node is None or list_node is None:
        raise ValueError("CLP 缺少 CLOTH_HEADER 或 CLOTH_WK_LIST")
    header: dict[str, object] = {name: _float(header_node, name) for name in CLP_HEADER_FLOATS}
    header.update({name: _int(header_node, name) for name in CLP_HEADER_INTS})
    header["gravityVec_"] = _vec4(header_node, "gravityVec_", (0.0, -0.001, 0.0, 1.0))
    nodes = []
    for item in list_node.findall("CLOTH_WK"):
        nodes.append(ClpNode(
            data_version=_int(item, "dataVersion_", 2), bone=_int(item, "no"),
            up=_int(item, "noUp", MISSING_BONE), down=_int(item, "noDown", MISSING_BONE),
            side=_int(item, "noSide", MISSING_BONE), poly=_int(item, "noPoly", MISSING_BONE),
            fix=_int(item, "noFix", MISSING_BONE), rotation_limit=_float(item, "rotLimit"),
            friction=_float(item, "friction"), gravity_blend_rate=_float(item, "gravityBlendRate_"),
            offset=_vec4(item, "offset", (0.0, 0.0, 0.0, 1.0)),
            original_rate=_float(item, "originalRate_"), weight=_float(item, "weight_", 1.0),
            thickness=_float(item, "thick_"), wind_area=_float(item, "windForceArea_"),
            joint_scale=_float(item, "jointScale_", 1.0),
            allow_change_scale=bool(_int(item, "bAllowChangeScale_")),
            axis_adjust_rate=_float(item, "axisAdjustRate_", 1.0),
        ))
    return ClpDocument(path=path, header=header, nodes=nodes)


def load_clh(path: str | Path) -> ClhDocument:
    path = Path(path)
    root = _tree(path, "CLOTH_AT").getroot()
    list_node = root.find("ClothCollision_LIST")
    if list_node is None:
        raise ValueError("CLH 缺少 ClothCollision_LIST")
    collisions = []
    for item in list_node.findall("ClothCollision"):
        collisions.append(ClhCollision(
            data_version=_int(item, "dataVersion_", 1), collision_id=_int(item, "id_"),
            p1=_int(item, "p1"), p2=_int(item, "p2"), weight=_float(item, "weight"),
            radius=_float(item, "radius"), offset1=_vec4(item, "offset1"),
            offset2=_vec4(item, "offset2"), capsule=_int(item, "capsule", -1),
            disabled_in_battle=bool(_int(item, "notUseInBattle")),
            disabled_in_idle=bool(_int(item, "notUseInIdle")),
        ))
    return ClhDocument(path=path, collisions=collisions)


def _set(parent: ET.Element, name: str, value: str) -> None:
    node = parent.find(name)
    if node is None:
        node = ET.SubElement(parent, name)
    node.text = value


def _format_float(value: float) -> str:
    return f"{float(value):.6f}"


def _format_vec4(value) -> str:
    return " ".join(_format_float(component) for component in value)


def _new_clp_node(template: ET.Element | None = None) -> ET.Element:
    if template is not None:
        return copy.deepcopy(template)
    node = ET.Element("CLOTH_WK")
    for name in (
        "dataVersion_", "no", "noUp", "noDown", "noSide", "noPoly", "noFix",
        "rotLimit", "friction", "gravityBlendRate_", "offset", "originalRate_",
        "weight_", "thick_", "windForceArea_", "jointScale_", "bAllowChangeScale_",
        "axisAdjustRate_",
    ):
        ET.SubElement(node, name)
    return node


def _atomic_write(tree: ET.ElementTree, path: Path) -> None:
    ET.indent(tree, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(handle)
    try:
        tree.write(temporary, encoding="utf-8", xml_declaration=False, short_empty_elements=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_clp(document: ClpDocument, path: str | Path | None = None) -> Path:
    destination = Path(path or document.path)
    tree = _tree(document.path, "CLOTH")
    root = tree.getroot()
    header_node = root.find("CLOTH_HEADER")
    list_node = root.find("CLOTH_WK_LIST")
    if header_node is None or list_node is None:
        raise ValueError("CLP 结构不完整")
    for name in CLP_HEADER_FLOATS:
        if name in document.header:
            _set(header_node, name, _format_float(document.header[name]))
    for name in CLP_HEADER_INTS:
        if name in document.header:
            _set(header_node, name, str(int(document.header[name])))
    if "gravityVec_" in document.header:
        _set(header_node, "gravityVec_", _format_vec4(document.header["gravityVec_"]))
    existing = {_int(node, "no", -1): node for node in list_node.findall("CLOTH_WK")}
    desired_ids = [int(value.bone) for value in document.nodes]
    if len(desired_ids) != len(set(desired_ids)):
        raise ValueError("CLP 节点包含重复骨骼 ID")
    desired = set(desired_ids)
    for old_id, node in tuple(existing.items()):
        if old_id not in desired:
            list_node.remove(node)
    template = next(iter(existing.values()), None)
    for value in document.nodes:
        node = existing.get(value.bone)
        if node is None:
            node = _new_clp_node(template)
            list_node.append(node)
            existing[value.bone] = node
        integers = {
            "dataVersion_": value.data_version, "no": value.bone, "noUp": value.up,
            "noDown": value.down, "noSide": value.side, "noPoly": value.poly,
            "noFix": value.fix, "bAllowChangeScale_": int(value.allow_change_scale),
        }
        floats = {
            "rotLimit": value.rotation_limit, "friction": value.friction,
            "gravityBlendRate_": value.gravity_blend_rate, "originalRate_": value.original_rate,
            "weight_": value.weight, "thick_": value.thickness,
            "windForceArea_": value.wind_area, "jointScale_": value.joint_scale,
            "axisAdjustRate_": value.axis_adjust_rate,
        }
        for name, item in integers.items(): _set(node, name, str(int(item)))
        for name, item in floats.items(): _set(node, name, _format_float(item))
        _set(node, "offset", _format_vec4(value.offset))
    _set(root, "CLOTH_WK_NUM", str(len(document.nodes)))
    _atomic_write(tree, destination)
    return destination


def _new_collision(parent: ET.Element) -> ET.Element:
    node = ET.SubElement(parent, "ClothCollision")
    for name in ("dataVersion_", "id_", "p1", "p2", "weight", "radius", "offset1", "offset2", "capsule", "notUseInBattle", "notUseInIdle"):
        ET.SubElement(node, name)
    return node


def write_clh(document: ClhDocument, path: str | Path | None = None) -> Path:
    destination = Path(path or document.path)
    tree = _tree(document.path, "CLOTH_AT")
    root = tree.getroot()
    list_node = root.find("ClothCollision_LIST")
    if list_node is None:
        raise ValueError("CLH 结构不完整")
    existing = {_int(node, "id_", -1): node for node in list_node.findall("ClothCollision")}
    desired_ids = {value.collision_id for value in document.collisions}
    for old_id, node in tuple(existing.items()):
        if old_id not in desired_ids:
            list_node.remove(node)
    for value in document.collisions:
        node = existing.get(value.collision_id)
        if node is None:
            node = _new_collision(list_node)
        integers = {
            "dataVersion_": value.data_version, "id_": value.collision_id,
            "p1": value.p1, "p2": value.p2, "capsule": value.capsule,
            "notUseInBattle": int(value.disabled_in_battle),
            "notUseInIdle": int(value.disabled_in_idle),
        }
        for name, item in integers.items(): _set(node, name, str(int(item)))
        _set(node, "weight", _format_float(value.weight))
        _set(node, "radius", _format_float(value.radius))
        _set(node, "offset1", _format_vec4(value.offset1))
        _set(node, "offset2", _format_vec4(value.offset2))
    _set(root, "CLOTH_AT_NUM", str(len(document.collisions)))
    _atomic_write(tree, destination)
    return destination
