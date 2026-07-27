"""Resolve GBFR Modtools workspace assets from a selected minfo file."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


class WorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClothFileRecord:
    category: str
    group_id: int
    source: Path
    xml: Path
    output: Path


@dataclass(frozen=True)
class AnimationAsset:
    name: str
    source: Path | None
    unpack: Path
    preview: Path


@dataclass(frozen=True)
class ModelBundle:
    workspace_json: Path
    workspace_root: Path
    character_id: str
    model_id: str
    prefer_source: bool
    texture_roots: tuple[Path, ...]
    minfo: Path
    skeleton: Path | None
    mmeshes: tuple[Path, ...]
    material_json: Path | None
    sop: Path | None
    sop_report: dict | None
    animations: tuple[AnimationAsset, ...]
    cloth_files: tuple[ClothFileRecord, ...]

    @property
    def mmesh(self) -> Path:
        """LOD0 compatibility alias for code not yet migrated to multi-LOD."""
        return self.mmeshes[0]


@dataclass(frozen=True)
class ModelExportTargets:
    workspace_json: Path
    workspace_root: Path
    model_id: str
    template_minfo: Path
    reference_skeleton: Path | None
    minfo: Path
    skeleton: Path | None
    mmeshes: tuple[Path, ...]

    @property
    def mmesh(self) -> Path:
        """LOD0 compatibility alias for the legacy single-mmesh exporter."""
        return self.mmeshes[0]


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve().samefile(right.resolve())
    except (FileNotFoundError, OSError):
        return str(left.resolve()).casefold() == str(right.resolve()).casefold()


def find_workspace_json(selected_path: str | Path) -> Path:
    selected = Path(selected_path).expanduser().resolve()
    current = selected.parent if selected.is_file() else selected
    for directory in (current, *current.parents):
        candidate = directory / "workspace.json"
        if candidate.is_file():
            return candidate
    raise WorkspaceError("所选 minfo 不在 GBFR Modtools 工作区中，向上未找到 workspace.json")


def _asset_path(root: Path, value: str | None) -> Path:
    if not value:
        return Path()
    path = Path(value)
    return path if path.is_absolute() else root / path


def _existing_asset_path(root: Path, record: dict, keys=("Input", "Source")) -> Path:
    candidates = [_asset_path(root, record.get(key)) for key in keys if record.get(key)]
    for path in candidates:
        if path.is_file():
            return path.resolve()
    if candidates:
        raise WorkspaceError(f"工作区资源不存在: {candidates[0]}")
    raise WorkspaceError("workspace.json 资源记录缺少路径")


def _selected_asset_path(root: Path, record: dict, prefer_source: bool) -> Path:
    """Resolve an import asset from the same source tree as the selected minfo."""
    keys = ("Source", "Input") if prefer_source else ("Input", "Source")
    return _existing_asset_path(root, record, keys=keys)


def _find_model_record(records: list[dict], file_type: str, stem: str) -> dict:
    matches = [
        record for record in records
        if str(record.get("FileType", "")).casefold() == file_type.casefold()
        and Path(record.get("Input") or record.get("Source") or "").stem.casefold() == stem.casefold()
    ]
    if len(matches) != 1:
        raise WorkspaceError(f"workspace.json 中无法唯一确定 {stem}.{file_type}")
    return matches[0]


def _find_optional_model_record(records: list[dict], file_type: str, stem: str) -> dict | None:
    matches = [
        record for record in records
        if str(record.get("FileType", "")).casefold() == file_type.casefold()
        and Path(record.get("Input") or record.get("Source") or "").stem.casefold() == stem.casefold()
    ]
    if len(matches) > 1:
        raise WorkspaceError(f"workspace.json 中无法唯一确定 {stem}.{file_type}")
    return matches[0] if matches else None


def _stream_record_order(record: dict) -> tuple[int, int, str]:
    value = str(record.get("Input") or record.get("Source") or "").replace("\\", "/")
    match = re.search(r"/(shadow)?lod(\d+)/", "/" + value.casefold().lstrip("/"))
    if match:
        return (1 if match.group(1) else 0, int(match.group(2)), value.casefold())
    return (2, 0, value.casefold())


def _find_mmesh_records(records: list[dict], model_id: str) -> list[dict]:
    matches = [
        record for record in records
        if str(record.get("FileType", "")).casefold() == "mmesh"
        and Path(record.get("Input") or record.get("Source") or "").stem.casefold() == model_id.casefold()
    ]
    if not matches:
        raise WorkspaceError(f"workspace.json 中未登记 {model_id}.mmesh")
    return sorted(matches, key=_stream_record_order)


def _read_workspace(workspace_json: str | Path) -> tuple[Path, Path, dict]:
    workspace_path = Path(workspace_json).expanduser().resolve()
    if not workspace_path.is_file():
        raise WorkspaceError(f"请选择存在的 workspace.json: {workspace_path}")
    try:
        document = json.loads(workspace_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkspaceError(f"无法读取 workspace.json: {error}") from error
    if int(document.get("Version", 0)) != 1:
        raise WorkspaceError(f"不支持的 workspace.json 版本: {document.get('Version')}")
    return workspace_path, workspace_path.parent, document


def _unpack_target(root: Path, unpack_root: Path, record: dict, file_type: str) -> Path:
    value = record.get("Input")
    if not value:
        raise WorkspaceError(f"{file_type} 记录缺少 unpack 输入路径")
    target = _asset_path(root, value).resolve()
    try:
        target.relative_to(unpack_root)
    except ValueError as error:
        raise WorkspaceError(f"{file_type} 输入路径不在工作区 unpack 中: {target}") from error
    return target


def resolve_model_export_targets(workspace_json: str | Path, model_id: str) -> ModelExportTargets:
    workspace_path, root, document = _read_workspace(workspace_json)
    model_id = str(model_id).strip()
    if not model_id:
        raise WorkspaceError("当前 minfo 会话缺少模型 ID")
    records = list(document.get("ModelFiles") or [])
    minfo_record = _find_model_record(records, "minfo", model_id)
    skeleton_record = _find_optional_model_record(records, "skeleton", model_id)
    mmesh_records = _find_mmesh_records(records, model_id)
    unpack_root = _asset_path(root, str(document.get("UnpackRoot") or "unpack")).resolve()
    return ModelExportTargets(
        workspace_json=workspace_path,
        workspace_root=root,
        model_id=model_id,
        template_minfo=_existing_asset_path(root, minfo_record),
        reference_skeleton=_existing_asset_path(root, skeleton_record, keys=("Source", "Input")) if skeleton_record else None,
        minfo=_unpack_target(root, unpack_root, minfo_record, "minfo"),
        skeleton=_unpack_target(root, unpack_root, skeleton_record, "skeleton") if skeleton_record else None,
        mmeshes=tuple(_unpack_target(root, unpack_root, record, "mmesh") for record in mmesh_records),
    )


def resolve_model_bundle(minfo_path: str | Path, workspace_json: str | Path | None = None) -> ModelBundle:
    selected = Path(minfo_path).expanduser().resolve()
    if selected.suffix.casefold() != ".minfo" or not selected.is_file():
        raise WorkspaceError(f"请选择存在的 .minfo 文件: {selected}")

    workspace_path, root, document = _read_workspace(workspace_json or find_workspace_json(selected))

    records = list(document.get("ModelFiles") or [])
    minfo_matches = []
    for record in records:
        if str(record.get("FileType", "")).casefold() != "minfo":
            continue
        candidates = [_asset_path(root, record.get(key)) for key in ("Input", "Source") if record.get(key)]
        if any(_same_path(selected, candidate) for candidate in candidates):
            minfo_matches.append(record)
    if len(minfo_matches) != 1:
        raise WorkspaceError("所选 minfo 未在 workspace.json 的 ModelFiles 中唯一登记")

    model_id = selected.stem
    minfo_record = minfo_matches[0]
    source_minfo = _asset_path(root, minfo_record.get("Source"))
    prefer_source = bool(source_minfo and _same_path(selected, source_minfo))
    minfo = _selected_asset_path(root, minfo_record, prefer_source)
    skeleton_record = _find_optional_model_record(records, "skeleton", model_id)
    skeleton = _selected_asset_path(root, skeleton_record, prefer_source) if skeleton_record else None
    mmeshes = tuple(
        _selected_asset_path(root, record, prefer_source)
        for record in _find_mmesh_records(records, model_id)
    )
    character_id = str(document.get("CharacterId") or model_id)
    source_root = _asset_path(root, str(document.get("SourceRoot") or "source"))
    unpack_root = _asset_path(root, str(document.get("UnpackRoot") or "unpack"))
    preferred_root, fallback_root = (
        (source_root, unpack_root) if prefer_source else (unpack_root, source_root)
    )

    material_candidates = []
    material_root = root / ("source" if prefer_source else "unpack") / "data" / "model" / model_id[:2] / model_id / "vars"
    material_candidates.append(material_root / "0.mmat.json")
    material_candidates.append(root / ("unpack" if prefer_source else "source") / "data" / "model" / model_id[:2] / model_id / "vars" / "0.mmat.json")
    material_json = next((path.resolve() for path in material_candidates if path.is_file()), None)

    sop_report = next(
        (record for record in document.get("SkeletonConstraints") or []
         if str(record.get("ModelId", "")).casefold() == model_id.casefold()),
        None,
    )
    sop_candidates = []
    if sop_report:
        for key in (("Source", "Input") if prefer_source else ("Input", "Source")):
            value = sop_report.get(key)
            if value:
                sop_candidates.append(_asset_path(root, value))
    for key in (("Source", "Input") if prefer_source else ("Input", "Source")):
        value = minfo_matches[0].get(key)
        if value:
            sop_candidates.append(_asset_path(root, value).with_suffix(".sop"))
    sop = next((path.resolve() for path in sop_candidates if path.is_file()), None)
    source_animation_root = source_root / "data" / model_id[:2] / model_id
    unpack_animation_root = unpack_root / "data" / model_id[:2] / model_id
    animation_names = set()
    for animation_root in (source_animation_root, unpack_animation_root):
        if animation_root.is_dir():
            animation_names.update(
                path.name for path in animation_root.glob("*.mot") if path.is_file()
            )
    animations = []
    for name in sorted(animation_names, key=str.casefold):
        source = source_animation_root / name
        unpack = unpack_animation_root / name
        source = source.resolve() if source.is_file() else None
        unpack = unpack.resolve()
        if prefer_source:
            preview = source or unpack
        else:
            preview = unpack if unpack.is_file() else source
        if preview is None:
            continue
        animations.append(AnimationAsset(name, source, unpack, preview))

    cloth_files = []
    for record in document.get("ClothFiles") or []:
        category = str(record.get("Category") or "").casefold()
        if category not in {"clp", "clh"}:
            continue
        xml = _asset_path(root, record.get("Xml"))
        source = _asset_path(root, record.get("Source"))
        output = _asset_path(root, record.get("Output"))
        if not xml.is_file():
            raise WorkspaceError(f"cloth 中间态不存在: {xml}")
        cloth_files.append(ClothFileRecord(
            category=category,
            group_id=int(record.get("GroupId", -1)),
            source=source.resolve(),
            xml=xml.resolve(),
            output=output.resolve(),
        ))
    cloth_files.sort(key=lambda item: (item.category, item.group_id, item.xml.name.casefold()))

    return ModelBundle(
        workspace_json=workspace_path,
        workspace_root=root,
        character_id=character_id,
        model_id=model_id,
        prefer_source=prefer_source,
        texture_roots=(preferred_root.resolve(), fallback_root.resolve()),
        minfo=minfo,
        skeleton=skeleton,
        mmeshes=mmeshes,
        material_json=material_json,
        sop=sop,
        sop_report=sop_report,
        animations=tuple(animations),
        cloth_files=tuple(cloth_files),
    )
