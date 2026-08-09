"""Clip tool: clips a child polygon to its own assigned parent's geometry."""

from ._engine import main
from ._tiling import subdivide_boundary

__all__ = ["main", "subdivide_boundary"]
