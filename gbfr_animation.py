"""PlatinumGames MOT parser used by the on-demand Blender preview."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import bisect
import math
import struct
import tempfile


_MOT_SUFFIX_ANNOTATIONS = {
    "030a": "闭左眼",
    "031a": "紧张闭眼",
    "032a": "闭右眼",
    "034a": "闭眼",
    "035a": "紧闭眼",
    "036a": "舒张闭眼",
    "e00a": "闭眼笑",
}


def guess_mot_annotation(name: str | Path) -> str:
    """Return a filename-based, explicitly speculative MOT description."""
    suffix = Path(str(name)).stem.casefold().rsplit("_", 1)[-1]
    annotation = _MOT_SUFFIX_ANNOTATIONS.get(suffix)
    if annotation is not None:
        return annotation
    if len(suffix) == 4 and suffix[0] == "c" and suffix[-1] == "b":
        try:
            value = int(suffix[1:3], 16)
        except ValueError:
            pass
        else:
            if 0x50 <= value <= 0x84:
                return "口型"
    return ""


@dataclass(frozen=True)
class AnimationKey:
    frame: int
    value: float
    in_tangent: float = 0.0
    out_tangent: float = 0.0


@dataclass(frozen=True)
class AnimationTrack:
    bone_id: int
    property: int
    compression: int
    unknown: int
    curve: str
    keys: tuple[AnimationKey, ...]

    def sample(self, frame: float) -> float:
        if not self.keys:
            return 0.0
        if self.curve == "constant" or frame <= self.keys[0].frame:
            return self.keys[0].value
        if frame >= self.keys[-1].frame:
            return self.keys[-1].value
        frames = [key.frame for key in self.keys]
        index = bisect.bisect_right(frames, frame)
        first, second = self.keys[index - 1], self.keys[index]
        span = float(second.frame - first.frame)
        if span <= 0.0:
            return second.value
        t = (frame - first.frame) / span
        if self.curve == "linear":
            return first.value + (second.value - first.value) * t
        t2, t3 = t * t, t * t * t
        return (
            (2.0 * t3 - 3.0 * t2 + 1.0) * first.value
            + (t3 - 2.0 * t2 + t) * first.out_tangent
            + (-2.0 * t3 + 3.0 * t2) * second.value
            + (t3 - t2) * second.in_tangent
        )


@dataclass(frozen=True)
class AnimationClip:
    path: Path
    version: int
    flags: int
    frame_count: int
    unknown: int
    name: str
    tracks: tuple[AnimationTrack, ...]


@dataclass(frozen=True)
class AnimationHeader:
    path: Path
    version: int
    flags: int
    frame_count: int
    track_count: int
    name: str


class _View:
    def __init__(self, path, limit=None):
        self.path = Path(path)
        with self.path.open("rb") as stream:
            self.data = stream.read() if limit is None else stream.read(limit)

    def require(self, offset, length, label):
        if offset < 0 or length < 0 or offset > len(self.data) or length > len(self.data) - offset:
            raise ValueError(f"{self.path.name}: {label} 越界 @ {offset}")

    def unpack(self, fmt, offset, label):
        size = struct.calcsize(fmt)
        self.require(offset, size, label)
        values = struct.unpack_from(fmt, self.data, offset)
        return values[0] if len(values) == 1 else values

    def fixed_string(self, offset, length):
        self.require(offset, length, "MOT 名称")
        return self.data[offset:offset + length].split(b"\0", 1)[0].decode("ascii", errors="replace")


def _read_header(view: _View) -> AnimationHeader:
    if view.unpack("<I", 0, "MOT magic") != 0x00746F6D:
        raise ValueError(f"{view.path.name}: MOT magic 无效")
    version = view.unpack("<I", 4, "MOT version")
    flags = view.unpack("<H", 8, "MOT flags")
    frames = view.unpack("<h", 10, "MOT frame count")
    if frames <= 0:
        raise ValueError(f"{view.path.name}: 帧数无效")
    count = view.unpack("<I", 16, "MOT track count")
    if count > 1_000_000:
        raise ValueError(f"{view.path.name}: 轨道数量不合理")
    return AnimationHeader(view.path.resolve(), version, flags, frames, count, view.fixed_string(24, 20))


def read_mot_header(path: str | Path) -> AnimationHeader:
    return _read_header(_View(path, 44))


def _pg_half_to_float(value: int) -> float:
    sign = (value & 0x8000) << 16
    source_exponent = (value & 0x7E00) >> 9
    source_mantissa = value & 0x01FF
    if not source_exponent and not source_mantissa:
        return struct.unpack("<f", struct.pack("<I", sign))[0]
    if source_exponent == 63:
        bits = sign | 0x7F800000 | (source_mantissa << 14)
    else:
        bits = sign | ((source_exponent + 80) << 23) | (source_mantissa << 14)
    return struct.unpack("<f", struct.pack("<I", bits))[0]


def _validate_keys(path, keys):
    for index, key in enumerate(keys):
        if not all(math.isfinite(value) for value in (key.value, key.in_tangent, key.out_tangent)):
            raise ValueError(f"{path.name}: MOT key 包含非有限值")
        if index and key.frame < keys[index - 1].frame:
            raise ValueError(f"{path.name}: MOT key 未按帧排序")


def load_mot(path: str | Path) -> AnimationClip:
    view = _View(path)
    header = _read_header(view)
    records_offset = view.unpack("<I", 12, "MOT records offset")
    unknown = view.unpack("<I", 20, "MOT unknown")
    view.require(records_offset, header.track_count * 12, "MOT record table")
    tracks = []
    for index in range(header.track_count):
        record = records_offset + index * 12
        bone_id = view.unpack("<h", record, "MOT bone id")
        prop = view.unpack("<b", record + 2, "MOT property")
        compression = view.unpack("<b", record + 3, "MOT compression")
        key_count = view.unpack("<h", record + 4, "MOT key count")
        track_unknown = view.unpack("<H", record + 6, "MOT track unknown")
        if key_count < 0:
            raise ValueError(f"{header.path.name}: 负 key 数量")
        if compression in (0, -1):
            keys = [AnimationKey(0, view.unpack("<f", record + 8, "MOT constant"))]
            tracks.append(AnimationTrack(bone_id, prop, compression, track_unknown, "constant", tuple(keys)))
            continue
        relative = view.unpack("<I", record + 8, "MOT data offset")
        data_offset = record + relative
        count = key_count
        keys = []
        curve = "linear" if compression in (1, 2, 3) else "hermite"
        if compression == 1:
            view.require(data_offset, count * 4, "MOT float curve")
            keys = [AnimationKey(frame, view.unpack("<f", data_offset + frame * 4, "MOT float key")) for frame in range(count)]
        elif compression == 2:
            view.require(data_offset, 8 + count * 2, "MOT u16 curve")
            base, step = view.unpack("<ff", data_offset, "MOT u16 base/step")
            keys = [AnimationKey(frame, base + step * view.unpack("<H", data_offset + 8 + frame * 2, "MOT u16 key")) for frame in range(count)]
        elif compression == 3:
            view.require(data_offset, 4 + count, "MOT u8 curve")
            base = _pg_half_to_float(view.unpack("<H", data_offset, "MOT u8 base"))
            step = _pg_half_to_float(view.unpack("<H", data_offset + 2, "MOT u8 step"))
            keys = [AnimationKey(frame, base + step * view.unpack("<B", data_offset + 4 + frame, "MOT u8 key")) for frame in range(count)]
        elif compression == 4:
            view.require(data_offset, count * 16, "MOT spline curve")
            for key_index in range(count):
                item = data_offset + key_index * 16
                keys.append(AnimationKey(view.unpack("<H", item, "MOT spline frame"), view.unpack("<f", item + 4, "MOT spline value"), view.unpack("<f", item + 8, "MOT spline in"), view.unpack("<f", item + 12, "MOT spline out")))
        elif compression == 5:
            view.require(data_offset, 24 + count * 8, "MOT u16 spline")
            bases = view.unpack("<6f", data_offset, "MOT u16 spline bases")
            for key_index in range(count):
                item = data_offset + 24 + key_index * 8
                keys.append(AnimationKey(view.unpack("<H", item, "MOT frame"), bases[0] + bases[1] * view.unpack("<H", item + 2, "MOT value"), bases[2] + bases[3] * view.unpack("<H", item + 4, "MOT in"), bases[4] + bases[5] * view.unpack("<H", item + 6, "MOT out")))
        elif compression in (6, 7):
            view.require(data_offset, 12 + count * 4, "MOT u8 spline")
            bases = tuple(_pg_half_to_float(view.unpack("<H", data_offset + item * 2, "MOT u8 spline base")) for item in range(6))
            absolute_frame = 0
            for key_index in range(count):
                item = data_offset + 12 + key_index * 4
                encoded = view.unpack("<B", item, "MOT frame")
                absolute_frame = absolute_frame + encoded if compression == 7 else encoded
                if absolute_frame > 0xFFFF:
                    raise ValueError(f"{header.path.name}: MOT frame 溢出")
                keys.append(AnimationKey(absolute_frame, bases[0] + bases[1] * view.unpack("<B", item + 1, "MOT value"), bases[2] + bases[3] * view.unpack("<B", item + 2, "MOT in"), bases[4] + bases[5] * view.unpack("<B", item + 3, "MOT out")))
        elif compression == 8:
            view.require(data_offset, 12 + count * 5, "MOT long spline")
            bases = tuple(_pg_half_to_float(view.unpack("<H", data_offset + item * 2, "MOT long base")) for item in range(6))
            for key_index in range(count):
                item = data_offset + 12 + key_index * 5
                frame = view.unpack(">H", item, "MOT long frame")
                keys.append(AnimationKey(frame, bases[0] + bases[1] * view.unpack("<B", item + 2, "MOT value"), bases[2] + bases[3] * view.unpack("<B", item + 3, "MOT in"), bases[4] + bases[5] * view.unpack("<B", item + 4, "MOT out")))
        else:
            raise ValueError(f"{header.path.name}: 不支持 MOT 压缩类型 {compression}")
        _validate_keys(header.path, keys)
        tracks.append(AnimationTrack(bone_id, prop, compression, track_unknown, curve, tuple(keys)))
    return AnimationClip(header.path, header.version, header.flags, header.frame_count, unknown, header.name, tuple(tracks))


def _float32(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("MOT 输出包含 NaN 或 Infinity")
    return struct.unpack("<f", struct.pack("<f", value))[0]


def serialize_mot_template(
    template: AnimationClip,
    sampled_tracks,
) -> bytes:
    """Serialize full-frame samples while preserving the template track contract."""
    if not 0 < int(template.frame_count) <= 0x7FFF:
        raise ValueError(f"MOT 帧数无法写入 int16: {template.frame_count}")
    if len(template.tracks) > 0xFFFFFFFF:
        raise ValueError("MOT 轨道数量过大")
    name = template.name.encode("ascii", errors="strict")
    if len(name) > 20:
        raise ValueError("MOT 内部名称超过 20 个 ASCII 字节")

    sampled_tracks = tuple(tuple(_float32(value) for value in values) for values in sampled_tracks)
    if len(sampled_tracks) != len(template.tracks):
        raise ValueError(
            f"MOT 采样轨道数量不一致: {len(sampled_tracks)} != {len(template.tracks)}"
        )
    for index, values in enumerate(sampled_tracks):
        if len(values) != template.frame_count:
            raise ValueError(
                f"MOT 轨道 {index} 采样帧数不一致: {len(values)} != {template.frame_count}"
            )

    records_offset = 44
    record_size = 12
    data = bytearray(records_offset + len(template.tracks) * record_size)
    struct.pack_into("<I", data, 0, 0x00746F6D)
    struct.pack_into("<I", data, 4, int(template.version))
    struct.pack_into("<H", data, 8, int(template.flags))
    struct.pack_into("<h", data, 10, int(template.frame_count))
    struct.pack_into("<I", data, 12, records_offset)
    struct.pack_into("<I", data, 16, len(template.tracks))
    struct.pack_into("<I", data, 20, int(template.unknown))
    data[24:24 + len(name)] = name

    for index, (track, values) in enumerate(zip(template.tracks, sampled_tracks)):
        record = records_offset + index * record_size
        first = values[0]
        if all(value == first for value in values[1:]):
            struct.pack_into(
                "<hbbhHf", data, record,
                int(track.bone_id), int(track.property), 0, 1, int(track.unknown), first,
            )
            continue

        data_offset = len(data)
        relative = data_offset - record
        struct.pack_into(
            "<hbbhHI", data, record,
            int(track.bone_id), int(track.property), 1,
            int(template.frame_count), int(track.unknown), relative,
        )
        data.extend(struct.pack(f"<{template.frame_count}f", *values))
    return bytes(data)


def write_mot_template_atomic(
    template: AnimationClip,
    sampled_tracks,
    destination: str | Path,
    *,
    verify_samples: bool = True,
    verify_indices=None,
) -> Path:
    """Write and reparse a template-based MOT before replacing its unpack target."""
    if not str(destination).strip():
        raise ValueError("MOT unpack 输出路径为空；请刷新动画列表后重试")
    destination = Path(destination).expanduser().resolve()
    if destination.suffix.casefold() != ".mot":
        raise ValueError(f"MOT unpack 输出目标不是 .mot 文件: {destination}")
    if destination.is_dir():
        raise ValueError(f"MOT unpack 输出目标是目录: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = serialize_mot_template(template, sampled_tracks)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp",
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        parsed = load_mot(temporary)
        if (
            parsed.version != template.version
            or parsed.flags != template.flags
            or parsed.frame_count != template.frame_count
            or parsed.unknown != template.unknown
            or parsed.name != template.name
            or len(parsed.tracks) != len(template.tracks)
        ):
            raise ValueError("MOT 临时文件头部或轨道数量往返不一致")
        for index, (source, output) in enumerate(zip(template.tracks, parsed.tracks)):
            if (
                output.bone_id != source.bone_id
                or output.property != source.property
                or output.unknown != source.unknown
            ):
                raise ValueError(f"MOT 临时文件轨道 {index} 契约往返不一致")
            if verify_samples or (verify_indices is not None and index in verify_indices):
                expected = sampled_tracks[index]
                actual = tuple(output.sample(frame) for frame in range(template.frame_count))
                if actual != tuple(_float32(value) for value in expected):
                    raise ValueError(f"MOT 临时文件轨道 {index} 采样往返不一致")
        os.replace(temporary, destination)
        temporary = None
        return destination
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
