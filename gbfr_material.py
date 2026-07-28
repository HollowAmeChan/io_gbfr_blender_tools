"""Parse base GBFR materials and resolve their workspace textures."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


ALBEDO_TEXTURE_SLOT_ID = 1059802457
EYE_HIGHLIGHT_TEXTURE_SLOT_ID = 11758192
EYE_IRIS_TEXTURE_SLOT_ID = 1668946419
EYE_CONJUNCTIVA_TEXTURE_SLOT_ID = 2933610414
ENABLE_ALPHA_PARAMETER_ID = 0x53F49792
_COLOR_VARIANT = re.compile(r"(?:^|_)c\d{2}(?:_|$)", re.IGNORECASE)
_KNOWN_TEXTURE_SLOTS = {
    "g_albedomap": ALBEDO_TEXTURE_SLOT_ID,
    "g_eyehighlighttexture": EYE_HIGHLIGHT_TEXTURE_SLOT_ID,
    "g_eyeiristexture": EYE_IRIS_TEXTURE_SLOT_ID,
    "g_eyewhitetexture": EYE_CONJUNCTIVA_TEXTURE_SLOT_ID,
}
_KNOWN_SHADER_PARAMETERS = {
    "g_53f49792_enablealpha_guessed": ENABLE_ALPHA_PARAMETER_ID,
}


class MaterialError(RuntimeError):
    pass


@dataclass(frozen=True)
class MaterialDefinition:
    material_id: int
    albedo_name: str | None
    eye_conjunctiva_name: str | None
    eye_iris_name: str | None
    eye_highlight_name: str | None
    alpha_enabled: bool

    @property
    def is_eye_material(self) -> bool:
        return bool(self.eye_conjunctiva_name and self.eye_iris_name and self.eye_highlight_name)


def is_color_variant_texture(name: str) -> bool:
    return bool(_COLOR_VARIANT.search(name))


def _known_hash(value, names: dict[str, int]) -> int | None:
    if isinstance(value, str):
        candidate = value.strip()
        known = names.get(candidate.casefold())
        if known is not None:
            return known
        try:
            return int(candidate, 0)
        except ValueError:
            return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value & 0xFFFFFFFF
    return None


def _read_texture_names(entry: dict, legacy: bool) -> dict[int, str]:
    textures = entry.get("A2" if legacy else "texture_maps")
    names = {}
    for texture in textures if isinstance(textures, list) else ():
        if not isinstance(texture, dict):
            continue
        candidate = str(texture.get("Name" if legacy else "texture_name") or "").strip()
        slot = _known_hash(
            texture.get("ID" if legacy else "shader_map_name_hash"),
            _KNOWN_TEXTURE_SLOTS,
        )
        if candidate and slot is not None and not is_color_variant_texture(candidate):
            names[slot] = candidate
    return names


def _alpha_enabled(entry: dict, legacy: bool) -> bool:
    parameters = entry.get("A1" if legacy else "shader_params")
    for parameter in parameters if isinstance(parameters, list) else ():
        if not isinstance(parameter, dict):
            continue
        parameter_id = _known_hash(
            parameter.get("ID" if legacy else "param_hash"),
            _KNOWN_SHADER_PARAMETERS,
        )
        value = parameter.get("ID2" if legacy else "value_or_offset", 0)
        if parameter_id == ENABLE_ALPHA_PARAMETER_ID and isinstance(value, (int, float)):
            return value != 0
    return False


def load_material_definitions(path: str | Path) -> tuple[MaterialDefinition, ...]:
    material_path = Path(path)
    try:
        document = json.loads(material_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise MaterialError(f"Cannot read material JSON {material_path}: {error}") from error

    legacy = "Entries1" in document
    entries = document.get("Entries1" if legacy else "materials")
    if not isinstance(entries, list):
        raise MaterialError(
            f"Material JSON has no materials or Entries1 array: {material_path}"
        )

    definitions = []
    for material_id, entry in enumerate(entries):
        entry = entry if isinstance(entry, dict) else {}
        texture_names = _read_texture_names(entry, legacy)
        definitions.append(MaterialDefinition(
            material_id=material_id,
            albedo_name=texture_names.get(ALBEDO_TEXTURE_SLOT_ID),
            eye_conjunctiva_name=texture_names.get(EYE_CONJUNCTIVA_TEXTURE_SLOT_ID),
            eye_iris_name=texture_names.get(EYE_IRIS_TEXTURE_SLOT_ID),
            eye_highlight_name=texture_names.get(EYE_HIGHLIGHT_TEXTURE_SLOT_ID),
            alpha_enabled=_alpha_enabled(entry, legacy),
        ))
    return tuple(definitions)


def resolve_albedo_texture(workspace_roots: str | Path | tuple[Path, ...], texture_name: str) -> Path | None:
    if isinstance(workspace_roots, (str, Path)):
        root = Path(workspace_roots)
        # Keep the legacy workspace-root API while allowing source/unpack roots
        # to be passed explicitly when resolving an imported model.
        if (root / "unpack").is_dir() or (root / "source").is_dir():
            roots = tuple(candidate for candidate in (root / "unpack", root / "source") if candidate.is_dir())
        else:
            roots = (root,)
    else:
        roots = tuple(Path(root) for root in workspace_roots)
    filenames = (f"{texture_name}.dds", f"{texture_name}_0.dds")
    for root in roots:
        directories = (
            root / "data/granite/2k",
            root / "data/texture/2k",
            root / "data/granite/4k",
            root / "data/texture/4k",
        )
        for directory in directories:
            for filename in filenames:
                candidate = directory / filename
                if candidate.is_file():
                    return candidate.resolve()
    return None
