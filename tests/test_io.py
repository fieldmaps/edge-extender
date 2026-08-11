"""Unit tests for core/io.py's remote-URL-aware path helpers."""

from pathlib import Path

from topo_tools.core.io import default_output_path, input_basename, resolve_input_path

_URL = "https://data.source.coop/hdx/cod-ab/lka/latest/adm2/original.parquet"


def test_resolve_input_path_keeps_url_unmangled():
    resolved = resolve_input_path(_URL)
    assert resolved == _URL
    assert isinstance(resolved, str)


def test_resolve_input_path_wraps_local_path():
    resolved = resolve_input_path("example.geojson")
    assert resolved == Path("example.geojson")


def test_input_basename_local_path():
    assert input_basename(Path("some/dir/original.parquet")) == "original.parquet"


def test_input_basename_url():
    assert input_basename(_URL) == "original.parquet"


def test_default_output_path_matches_with_stem_for_local_input():
    local = Path("some/dir/original.parquet")
    assert default_output_path(local, "_extended") == local.with_stem(
        local.stem + "_extended"
    )


def test_default_output_path_defaults_to_cwd_for_url_input():
    assert default_output_path(_URL, "_extended") == Path("original_extended.parquet")
