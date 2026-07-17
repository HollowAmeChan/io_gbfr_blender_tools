"""Resolve GBFR Modtools workspace assets from a selected minfo file."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


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
class ModelBundle:
    workspace_json: Path
    workspace_root: Path
    character_id: str
    model_id: str
    minfo: Path
    skeleton: Path
    mmesh: Path
    sop: Path | None
    sop_report: dict | None
    cloth_files: tuple[ClothFileRecord, ...]
    data_tools: Path | None


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


def _find_model_record(records: list[dict], file_type: str, stem: str) -> dict:
    matches = [
        record for record in records
        if str(record.get("FileType", "")).casefold() == file_type.casefold()
        and Path(record.get("Input") or record.get("Source") or "").stem.casefold() == stem.casefold()
    ]
    if len(matches) != 1:
        raise WorkspaceError(f"workspace.json 中无法唯一确定 {stem}.{file_type}")
    return matches[0]


def _find_data_tools(workspace_root: Path) -> Path | None:
    for directory in (workspace_root, *workspace_root.parents):
        candidate = directory / "_lib" / "tools" / "GBFRDataTools" / "GBFRDataTools.exe"
        if candidate.is_file():
            return candidate.resolve()
    return None


def resolve_model_bundle(minfo_path: str | Path, workspace_json: str | Path | None = None) -> ModelBundle:
    selected = Path(minfo_path).expanduser().resolve()
    if selected.suffix.casefold() != ".minfo" or not selected.is_file():
        raise WorkspaceError(f"请选择存在的 .minfo 文件: {selected}")

    workspace_path = Path(workspace_json).resolve() if workspace_json else find_workspace_json(selected)
    root = workspace_path.parent
    try:
        document = json.loads(workspace_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkspaceError(f"无法读取 workspace.json: {error}") from error
    if int(document.get("Version", 0)) != 1:
        raise WorkspaceError(f"不支持的 workspace.json 版本: {document.get('Version')}")

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
    minfo = _existing_asset_path(root, minfo_matches[0])
    skeleton = _existing_asset_path(root, _find_model_record(records, "skeleton", model_id))
    mmesh = _existing_asset_path(root, _find_model_record(records, "mmesh", model_id))
    character_id = str(document.get("CharacterId") or model_id)

    sop_report = next(
        (record for record in document.get("SkeletonConstraints") or []
         if str(record.get("ModelId", "")).casefold() == model_id.casefold()),
        None,
    )
    sop_candidates = []
    if sop_report and sop_report.get("Source"):
        sop_candidates.append(_asset_path(root, sop_report["Source"]))
    for key in ("Source", "Input"):
        value = minfo_matches[0].get(key)
        if value:
            sop_candidates.append(_asset_path(root, value).with_suffix(".sop"))
    sop = next((path.resolve() for path in sop_candidates if path.is_file()), None)

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
        minfo=minfo,
        skeleton=skeleton,
        mmesh=mmesh,
        sop=sop,
        sop_report=sop_report,
        cloth_files=tuple(cloth_files),
        data_tools=_find_data_tools(root),
    )
