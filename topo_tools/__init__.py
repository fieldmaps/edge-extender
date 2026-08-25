"""topo-tools: DuckDB-powered geospatial topology utilities."""

from .api import (
    change,
    dissolve,
    edge_clip,
    edge_extend,
    edge_match,
    edge_mosaic,
    edge_stitch,
    schema_crosswalk,
    schema_fill,
    schema_map,
    schema_refactor,
    topo_clean,
    topo_detect,
)
from .cli.main import cli

__all__ = [
    "change",
    "cli",
    "dissolve",
    "edge_clip",
    "edge_extend",
    "edge_match",
    "edge_mosaic",
    "edge_stitch",
    "schema_crosswalk",
    "schema_fill",
    "schema_map",
    "schema_refactor",
    "topo_clean",
    "topo_detect",
]
