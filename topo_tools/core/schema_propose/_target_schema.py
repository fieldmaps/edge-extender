"""Loads a target-schema YAML config into structured field definitions."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class TargetField:
    """One canonical target field, optionally repeatable across admin levels."""

    name: str
    aliases: tuple[str, ...] = ()
    patterns: tuple[re.Pattern, ...] = ()
    repeatable: tuple[int, int] | None = None


def normalize(value: str) -> str:
    """Case/whitespace/punctuation-insensitive form, for exact/alias comparison."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def load_target_schema(path: Path | str) -> list[TargetField]:
    """Load a target-schema YAML file into a list of TargetField."""
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict) or "fields" not in data:
        msg = f"target schema must be a mapping with a top-level 'fields' key: {path}"
        raise ValueError(msg)

    fields = []
    for raw in data["fields"]:
        if "name" not in raw:
            msg = f"target schema field entry missing required 'name' key: {path}"
            raise ValueError(msg)
        repeatable = raw.get("repeatable")
        if repeatable is not None and (
            "min" not in repeatable or "max" not in repeatable
        ):
            msg = (
                f"target schema field {raw['name']!r} repeatable block "
                f"missing min/max: {path}"
            )
            raise ValueError(msg)
        level_range = (repeatable["min"], repeatable["max"]) if repeatable else None
        fields.append(
            TargetField(
                name=raw["name"],
                aliases=tuple(raw.get("aliases", [])),
                patterns=tuple(
                    re.compile(p, re.IGNORECASE) for p in raw.get("patterns", [])
                ),
                repeatable=level_range,
            )
        )
    return fields
