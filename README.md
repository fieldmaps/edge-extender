# topo-tools

[![CI](https://github.com/OCHA-DAP/topo-tools-py/actions/workflows/ci.yml/badge.svg)](https://github.com/OCHA-DAP/topo-tools-py/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/topo-tools)](https://pypi.org/project/topo-tools/)
[![Python versions](https://img.shields.io/pypi/pyversions/topo-tools)](https://pypi.org/project/topo-tools/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

![World ADM0 boundaries extended with Voronoi-filled coastline](https://raw.githubusercontent.com/OCHA-DAP/topo-tools-py/main/img/wld_01.png)

`topo-tools` is a collection of DuckDB-powered geospatial topology utilities
for cleaning and reconciling administrative boundary polygons. It ships
thirteen tools, usable from the CLI or as a Python package. Composite tools
are nested under the primitives they chain internally; every primitive is
also usable standalone:

- **[schema-crosswalk](docs/explanation/schema_crosswalk.md)**: infers a source-column to target-schema crosswalk and immediately applies it, in one call.
  - **[schema-map](docs/explanation/schema_map.md)**: infers a polygon layer's admin hierarchy structurally and proposes a source to target-schema crosswalk for review.
  - **[schema-refactor](docs/explanation/schema_refactor.md)**: applies a crosswalk CSV, from schema-map or hand-edited, to rename or drop columns. Geometry passes through unchanged.
- **[schema-fill](docs/explanation/schema_fill.md)**: cascades each admin-hierarchy column down from its nearest non-NULL shallower level and stamps a depth column.
- **[topo-clean](docs/explanation/topo_clean.md)**: detects and fixes gap/overlap defects in a single polygon layer, reporting issues for manual review.
  - **[topo-detect](docs/explanation/topo_detect.md)**: scans a single polygon layer for gap/overlap coverage defects and reports them, without fixing anything.
- **[edge-match](docs/explanation/edge_match.md)**: fits a finer child polygon layer into a coarser parent layer, grouping and extending each child to fill gaps within its own parent.
  - **[edge-extend](docs/explanation/edge_extend.md)**: fills gaps around a polygon layer (missing coastline, disputed areas, water bodies) with a Voronoi extension, producing full coverage.
  - **[edge-mosaic](docs/explanation/edge_mosaic.md)**: re-clips an already-extended child layer into a new/different parent layer, skipping Voronoi extension entirely.
    - **[edge-clip](docs/explanation/edge_clip.md)**: assigns each child to its parent, then clips it to that parent's geometry.
    - **[edge-stitch](docs/explanation/edge_stitch.md)**: closes seams in an already-tiled polygon layer with one whole-table coverage-clean pass.
- **[change](docs/explanation/change.md)**: compares two versions of a polygon layer and classifies every unit as unchanged, renamed, modified, split, merged, created, or removed.
- **[dissolve](docs/explanation/dissolve.md)**: aggregates a polygon layer into a coarser one by grouping on attribute columns and unioning geometry per group.

## Installation

Install with `uv` (recommended):

```sh
uv tool install topo-tools   # CLI
uv add topo-tools            # Python library
```

Or with `pip`/`pipx`:

```sh
pip install topo-tools       # CLI or library
pipx install topo-tools      # CLI
```

On macOS/Linux, `topo-tools` is also available via Homebrew, no Python
tooling required:

```sh
brew install OCHA-DAP/topo-tools/topo-tools
```

Each linked doc above covers that tool's CLI/Python usage, options, and examples.

## Supported Formats

Polygon inputs/outputs: GeoParquet (`.parquet`), GeoPackage (`.gpkg`),
Shapefile (`.shp`), GeoJSON (`.geojson`). Output format matches input format.
`change`'s tabular changelog is CSV or GeoParquet only; its spatial overlay
layer supports the same four formats as the other tools.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development setup.
