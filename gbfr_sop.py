"""GBFR skeleton operation (SOP) parser and guarded core evaluation."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import struct


SOP_VERSION = 0x20200309
TARGET_BONE_PROPERTY = 0x5B0292DD
SOURCE_BONE_PROPERTY = 0x1B5B0525
SWING_TWIST_OPERATION = 0xB1FFF4E6
TWIST_OPERATION = 0x61D80537
COMMON_ZERO_PROPERTY = 0x64DE2725
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


def _float_property(property_hash: int, value: float) -> SopProperty:
    if not math.isfinite(float(value)):
        raise ValueError("SOP 浮点属性必须是有限值")
    raw = struct.unpack("<I", struct.pack("<f", float(value)))[0]
    return SopProperty(property_hash, 1, raw)


def make_swing_twist_operation(
    target_bone: int,
    source_bone: int,
    axis: int,
    swing_rate: float,
    twist_rate: float,
    *,
    index: int = -1,
) -> SopOperation:
    if axis not in {0, 1, 2}:
        raise ValueError("SOP 旋转轴必须是 X、Y 或 Z")
    if target_bone < 0 or source_bone < 0:
        raise ValueError("SOP target/source 骨骼 ID 无效")
    axes = tuple(1.0 if value == axis else 0.0 for value in range(3))
    return SopOperation(
        index=index,
        type_hash=SWING_TWIST_OPERATION,
        metadata=0x00090101,
        target_bone=int(target_bone),
        source_bone=int(source_bone),
        properties=(
            SopProperty(COMMON_ZERO_PROPERTY, 0, 0),
            _float_property(AXIS_X_PROPERTY, axes[0]),
            _float_property(AXIS_Y_PROPERTY, axes[1]),
            _float_property(AXIS_Z_PROPERTY, axes[2]),
            _float_property(TWIST_RATE_PROPERTY, twist_rate),
            _float_property(SWING_RATE_PROPERTY, swing_rate),
            _float_property(OFFSET_X_PROPERTY, 0.0),
            _float_property(OFFSET_Y_PROPERTY, 0.0),
            _float_property(OFFSET_Z_PROPERTY, 0.0),
        ),
    )


def is_editable_swing_twist(operation: SopOperation) -> bool:
    required = (
        AXIS_X_PROPERTY, AXIS_Y_PROPERTY, AXIS_Z_PROPERTY,
        TWIST_RATE_PROPERTY, SWING_RATE_PROPERTY,
    )
    return operation.type_hash == SWING_TWIST_OPERATION and all(
        (value := operation.find(property_hash)) is not None and value.value_type == 1
        for property_hash in required
    )


def update_swing_twist_operation(
    operation: SopOperation,
    *,
    target_bone: int,
    source_bone: int,
    axis: int,
    swing_rate: float,
    twist_rate: float,
) -> SopOperation:
    if not is_editable_swing_twist(operation):
        raise ValueError("只能编辑字段完整的 Swing/Twist SOP 操作")
    if axis not in {0, 1, 2}:
        raise ValueError("SOP 旋转轴必须是 X、Y 或 Z")
    if target_bone < 0 or source_bone < 0:
        raise ValueError("SOP target/source 骨骼 ID 无效")
    replacements = {
        AXIS_X_PROPERTY: 1.0 if axis == 0 else 0.0,
        AXIS_Y_PROPERTY: 1.0 if axis == 1 else 0.0,
        AXIS_Z_PROPERTY: 1.0 if axis == 2 else 0.0,
        SWING_RATE_PROPERTY: swing_rate,
        TWIST_RATE_PROPERTY: twist_rate,
    }
    properties = tuple(
        _float_property(value.hash, replacements[value.hash]) if value.hash in replacements else value
        for value in operation.properties
    )
    return SopOperation(
        index=operation.index,
        type_hash=operation.type_hash,
        metadata=operation.metadata,
        target_bone=int(target_bone),
        source_bone=int(source_bone),
        properties=properties,
    )


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


def encode_sop(asset: SopAsset) -> bytes:
    if asset.version != SOP_VERSION:
        raise ValueError(f"不支持的 SOP 版本 0x{asset.version:08X}")
    if len(asset.operations) > 100_000:
        raise ValueError("SOP 操作数量不合理")

    records = []
    for operation in asset.operations:
        if len(operation.properties) > 0xFF:
            raise ValueError("单条 SOP 操作属性超过 255 个")
        if not 0 <= operation.target_bone <= 0xFFFFFFFF or not 0 <= operation.source_bone <= 0xFFFFFFFF:
            raise ValueError("SOP target/source 骨骼 ID 越界")
        metadata = (operation.metadata & ~0x00FF0000) | (len(operation.properties) << 16)
        record = bytearray(struct.pack(
            "<6I", operation.type_hash, metadata,
            TARGET_BONE_PROPERTY, operation.target_bone,
            SOURCE_BONE_PROPERTY, operation.source_bone,
        ))
        for value in operation.properties:
            if value.value_type not in {0, 1}:
                raise ValueError(f"SOP 属性类型 {value.value_type} 不支持")
            record.extend(struct.pack("<3I", value.hash, value.value_type, value.raw_value))
        records.append(bytes(record))

    header_size = 12 + len(records) * 4
    offsets = []
    offset = header_size
    for record in records:
        offsets.append(offset)
        offset += len(record)
    header = bytearray(struct.pack("<4sII", b"sop\0", asset.version, len(records)))
    if offsets:
        header.extend(struct.pack(f"<{len(offsets)}I", *offsets))
    return bytes(header) + b"".join(records)


def _atomic_write(path: Path, data: bytes) -> Path:
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def save_sop(path: str | Path, asset: SopAsset) -> Path:
    return _atomic_write(Path(path), encode_sop(asset))


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
