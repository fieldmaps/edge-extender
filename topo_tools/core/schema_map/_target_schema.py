"""Loads a target-schema YAML config: the output naming templates for map."""

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_TARGET_SCHEMA_PATH = Path(__file__).parent / "data" / "cod-ab.yaml"


@dataclass(frozen=True)
class TargetSchema:
    """Output naming templates for a discovered hierarchy level `n`."""

    name_field: str
    code_field: str


def load_target_schema(path: Path | str) -> TargetSchema:
    """Load a target-schema YAML file into a TargetSchema."""
    data = yaml.safe_load(Path(path).read_text())
    if (
        not isinstance(data, dict)
        or "name_field" not in data
        or "code_field" not in data
    ):
        msg = (
            "target schema must be a mapping with top-level 'name_field' and "
            f"'code_field' keys: {path}"
        )
        raise ValueError(msg)

    name_field, code_field = data["name_field"], data["code_field"]
    if "{n}" not in name_field or "{n}" not in code_field:
        msg = f"name_field/code_field must both contain a '{{n}}' placeholder: {path}"
        raise ValueError(msg)
    return TargetSchema(name_field=name_field, code_field=code_field)
