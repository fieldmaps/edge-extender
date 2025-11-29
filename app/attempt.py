from decimal import Decimal
from pathlib import Path
from venv import logger

from psycopg import Connection
from psycopg.errors import InternalError_

from . import points, voronoi
from .utils import config, get_config, truthy


def main(conn: Connection, name: str, file: Path, layer: str, *_: list) -> None:  # noqa: C901
    """Try to generate voronoi polygons with multiple parameters.

    First try running with default settings, segmentation and no snapping.
    If that fails, then try doubling the segmentation distance to avoid memory errors.

    Finally, loop through sequential segment and snap values to find the best threshold.
    Starting with the default segment, start incrementing snap values like so:
    ...01, ...02, ...03, 04, 05, 06, 07, 08, 09, 10, 20, 30, 40, 50, 60, 70, 80, 90
    If all those snap values fail, releat for segment values like so:
    ...1, ...2, ...3, 4, 5, 6, 7, 8, 9
    """
    base = 1
    segment = get_config(name)["segment"]
    for n in [base, base * 2]:
        segment_0 = str(Decimal(segment) * n)
        try:
            points.main(conn, name, file, layer, segment_0, "")
            voronoi.main(conn, name)
            if n != base:
                logger.info(f"success: {name} segment={segment_0}")
        except (RuntimeError, InternalError_) as e:
            if config["verbose"].lower() in truthy:
                logger.error(f"fail: {name} segment={segment_0}, {e}")
        else:
            return
    error = f"{name} did not succeed generating voronoi polygons"
    if config["retry"].lower() in truthy:
        snap = get_config(name)["snap"]
        for z in range(9):
            for y in [1, 10]:
                for x in range(9):
                    segment_1 = str(Decimal(segment) * (z + 1))
                    snap_1 = str(Decimal(snap) * (x + 1) * y)
                    try:
                        points.main(conn, name, file, layer, segment_1, snap_1)
                        voronoi.main(conn, name)
                        logger.info(
                            f"success: {name} segment={segment_1} snap={snap_1}",
                        )
                    except (RuntimeError, InternalError_) as e:
                        if config["verbose"].lower() in truthy:
                            logger.error(
                                f"fail: {name} segment={segment_1} snap={snap_1}, {e}",
                            )
                    else:
                        return
                    error = (
                        f"{name} did not succeed generating voronoi polygons "
                        f"with segment={segment}-{segment_1} and snap={snap}-{snap_1}"
                    )
    logger.error(error)
    raise RuntimeError(error)
