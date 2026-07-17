"""GBFR skeleton operation (SOP) parser and guarded core evaluation."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import struct


SOP_VERSION = 0x20200309
TARGET_BONE_PROPERTY = 0x5B0292DD
SOURCE_BONE_PROPERTY = 0x1B5B0525
SWING_TWIST_OPERATION = 0xB1FFF4E6
TWIST_OPERATION = 0x61D80537
AXIS_X_PROPERTY = 0x2E933545
AXIS_Y_PROPERTY = 0x599405D3
AXIS_Z_PROPERTY = 0xC09D5469
TWIST_RATE_PROPERTY = 0x72B10DA8
SWING_RATE_PROPERTY = 0x9BE488F1
OFFSET_X_PROPERTY = 0x597EA425
OFFSET_Y_PROPERTY = 0x2E7994B3
OFFSET_Z_PROPERTY = 0xB770C509


@dataclass(frozen=True)
class SopProperty:
    hash: int
    value_type: int
    raw_value: int

    @property
    def value(self) -> int | float:
        return struct.unpack("<f", struct.pack("<I", self.raw_value))[0] if self.value_type == 1 else self.raw_value


@dataclass(frozen=True)
class SopOperation:
    index: int
    type_hash: int
    metadata: int
    target_bone: int
    source_bone: int
    properties: tuple[SopProperty, ...]

    def find(self, property_hash: int) -> SopProperty | None:
        return next((item for item in self.properties if item.hash == property_hash), None)

    def floating(self, property_hash: int, default: float | None = None) -> float | None:
        value = self.find(property_hash)
        if value is None:
            return default
        if value.value_type != 1 or not math.isfinite(float(value.value)):
            return None
        return float(value.value)


@dataclass(frozen=True)
class SopAsset:
    path: Path
    version: int
    operations: tuple[SopOperation, ...]


@dataclass(frozen=True)
class SopDescription:
    name: str = "未知操作"
    category: str = "Unknown"
    discovery: str = "unknown"
    discovery_label: str = "未探明"
    runtime: str = "not_implemented"
    runtime_label: str = "未实现"
    purpose: str = "没有该操作的用途记录；原始属性仍会保留。"


def load_sop(path: str | Path) -> SopAsset:
    path = Path(path)
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"sop\0":
        raise ValueError(f"{path.name} 不是有效 SOP")
    version, count = struct.unpack_from("<II", data, 4)
    if version != SOP_VERSION:
        raise ValueError(f"不支持的 SOP 版本 0x{version:08X}")
    if count > 100_000:
        raise ValueError("SOP 操作数量不合理")
    table_end = 12 + count * 4
    if table_end > len(data):
        raise ValueError("SOP 偏移表越界")
    offsets = list(struct.unpack_from(f"<{count}I", data, 12)) if count else []
    for index, offset in enumerate(offsets):
        if offset < table_end or offset >= len(data) or (index and offset <= offsets[index - 1]):
            raise ValueError(f"SOP 操作 #{index} 偏移无效")

    operations = []
    for index, begin in enumerate(offsets):
        end = offsets[index + 1] if index + 1 < count else len(data)
        length = end - begin
        if length < 24 or (length - 24) % 12:
            raise ValueError(f"SOP 操作 #{index} 长度无效")
        type_hash, metadata, target_key, target, source_key, source = struct.unpack_from("<6I", data, begin)
        if target_key != TARGET_BONE_PROPERTY or source_key != SOURCE_BONE_PROPERTY:
            raise ValueError(f"SOP 操作 #{index} target/source 字段无效")
        property_count = (metadata >> 16) & 0xFF
        if property_count != (length - 24) // 12:
            raise ValueError(f"SOP 操作 #{index} 属性数量不符")
        properties = []
        for property_index in range(property_count):
            item = struct.unpack_from("<3I", data, begin + 24 + property_index * 12)
            if item[1] > 1:
                raise ValueError(f"SOP 操作 #{index} 属性类型 {item[1]} 不支持")
            properties.append(SopProperty(*item))
        operations.append(SopOperation(index, type_hash, metadata, target, source, tuple(properties)))
    return SopAsset(path.resolve(), version, tuple(operations))


def load_catalog(path: str | Path) -> dict[int, SopDescription]:
    document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    result = {}
    for item in document.get("Operations", []):
        value = int(item["Hash"], 16)
        result[value] = SopDescription(
            name=str(item.get("Name", "未知操作")), category=str(item.get("Category", "Unknown")),
            discovery=str(item.get("Discovery", "unknown")),
            discovery_label=str(item.get("DiscoveryLabel", "未探明")),
            runtime=str(item.get("Runtime", "not_implemented")),
            runtime_label=str(item.get("RuntimeLabel", "未实现")),
            purpose=str(item.get("Purpose", "没有用途记录")),
        )
    return result


def _normalize(value):
    length = math.sqrt(sum(component * component for component in value))
    return (1.0, 0.0, 0.0, 0.0) if length < 1e-8 else tuple(component / length for component in value)


def _multiply(left, right):
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )


def _power(value, rate):
    value = _normalize(value)
    if value[0] < 0.0:
        value = tuple(-component for component in value)
    half_angle = math.acos(max(-1.0, min(1.0, value[0])))
    sine = math.sin(half_angle)
    if abs(sine) < 1e-7:
        return (1.0, 0.0, 0.0, 0.0)
    scaled = half_angle * rate
    vector_scale = math.sin(scaled) / sine
    return _normalize((math.cos(scaled), value[1] * vector_scale, value[2] * vector_scale, value[3] * vector_scale))


def _euler_quaternion(x, y, z):
    sx, cx = math.sin(x * 0.5), math.cos(x * 0.5)
    sy, cy = math.sin(y * 0.5), math.cos(y * 0.5)
    sz, cz = math.sin(z * 0.5), math.cos(z * 0.5)
    return _normalize((
        cx * cy * cz + sx * sy * sz,
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
    ))


def evaluate_core_operation(operation: SopOperation, source_wxyz) -> tuple[float, float, float, float] | None:
    if operation.type_hash not in {SWING_TWIST_OPERATION, TWIST_OPERATION}:
        return None
    axis_values = tuple(operation.floating(value) for value in (AXIS_X_PROPERTY, AXIS_Y_PROPERTY, AXIS_Z_PROPERTY))
    twist_rate = operation.floating(TWIST_RATE_PROPERTY)
    if any(value is None for value in axis_values) or twist_rate is None:
        return None
    axis_length = math.sqrt(sum(float(value) ** 2 for value in axis_values))
    if axis_length < 1e-8:
        return None
    axis = tuple(float(value) / axis_length for value in axis_values)
    source = _normalize(tuple(float(value) for value in source_wxyz))
    projection = sum(source[index + 1] * axis[index] for index in range(3))
    twist = _normalize((source[0], axis[0] * projection, axis[1] * projection, axis[2] * projection))
    if operation.type_hash == SWING_TWIST_OPERATION:
        swing_rate = operation.floating(SWING_RATE_PROPERTY)
        if swing_rate is None:
            return None
        swing = _normalize(_multiply(source, (twist[0], -twist[1], -twist[2], -twist[3])))
        base = _multiply(_power(swing, swing_rate), _power(twist, twist_rate))
    else:
        base = _power(twist, twist_rate)
    offset = _euler_quaternion(
        operation.floating(OFFSET_X_PROPERTY, 0.0) or 0.0,
        operation.floating(OFFSET_Y_PROPERTY, 0.0) or 0.0,
        operation.floating(OFFSET_Z_PROPERTY, 0.0) or 0.0,
    )
    return _normalize(_multiply(base, offset))


def quaternion_error(left, right) -> float:
    left, right = _normalize(left), _normalize(right)
    minus = math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))
    plus = math.sqrt(sum((a + b) ** 2 for a, b in zip(left, right)))
    return min(minus, plus)


def guarded_preview_status(operation: SopOperation, rest_quaternions: dict[int, tuple[float, ...]]) -> str:
    if operation.type_hash not in {SWING_TWIST_OPERATION, TWIST_OPERATION}:
        return "not_implemented"
    source = rest_quaternions.get(operation.source_bone)
    target = rest_quaternions.get(operation.target_bone)
    if source is None or target is None:
        return "missing_bone"
    output = evaluate_core_operation(operation, source)
    if output is None:
        return "invalid_core_fields"
    return "approximate_constraint" if quaternion_error(output, target) <= 1e-4 else "rest_guard_failed"


def dominant_axis(operation: SopOperation) -> int | None:
    values = tuple(operation.floating(value) for value in (AXIS_X_PROPERTY, AXIS_Y_PROPERTY, AXIS_Z_PROPERTY))
    if any(value is None for value in values) or max(abs(float(value)) for value in values) < 1e-8:
        return None
    return max(range(3), key=lambda index: abs(float(values[index])))
