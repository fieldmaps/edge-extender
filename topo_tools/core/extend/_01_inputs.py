"""Imports geodata, reprojects to EPSG:4326, and cleans coverage violations."""

from logging import getLogger
from pathlib import Path

from duckdb import DuckDBPyConnection

from topo_tools.core.coverage import coverage_clean, has_coverage_violations
from topo_tools.core.io import read_and_reproject

logger = getLogger(__name__)


def main(conn: DuckDBPyConnection, name: str, path: Path) -> None:
    """Import geodata into DuckDB tables, then clean coverage topology violations.

    ST_CoverageInvalidEdges_Agg gates whether ST_CoverageClean runs at all —
    no-op when the input coverage has no invalid edges. Otherwise every
    polygon's coordinates may shift, not just the violating ones. Does not
    distinguish real holes from digitization slivers: inputs are expected to
    be pre-cleaned upstream, and any narrow gap that slips through is treated
    the same as a real hole (lake, enclave) — both are legitimate work for
    the Voronoi-extension stage to divide across bordering polygons.
    """
    read_and_reproject(conn, name, path)

    if has_coverage_violations(conn, f"{name}_01"):
        logger.info("cleaning coverage: invalid edges detected")
        coverage_clean(
            conn, f"{name}_01", f"{name}_01", fids=None, gap_maximum_width=None
        )
