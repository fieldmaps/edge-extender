from decimal import Decimal
from venv import logger

from . import points, voronoi
from .utils import config, get_config


def main(conn, name, file, layer, *_):
    """Inteligently rety segment and snap values.

    Using default snap values, will try 0.00000{1-9}, then 0.0000{1-9}
    at segment=0.0001 before moving on to segment=0.0002
    """
    segment = get_config(name)["segment"]
    snap = get_config(name)["snap"]
    if config["retry"].lower() in ("yes", "on", "true", "1"):
        for z in range(9):
            for y in [1, 10]:
                for x in range(9):
                    segment_1 = Decimal(segment) * (z + 1)
                    snap_1 = Decimal(snap) * (x + 1) * y
                    try:
                        points.main(conn, name, file, layer, segment_1, snap_1)
                        voronoi.main(conn, name, file, layer)
                        if str(segment_1) != segment or str(snap_1) != snap:
                            logger.info(
                                f"success: {name} segment={segment_1} snap={snap_1}"
                            )
                        return
                    except Exception:
                        if config["verbose"].lower() in ("yes", "on", "true", "1"):
                            logger.info(
                                f"fail: {name} segment={segment_1} snap={snap_1}"
                            )
        error = (
            f"{name} did not succeed from segment={segment}-{segment_1} and "
            f"snap={snap}-{snap_1}"
        )
        logger.error(error)
        raise RuntimeError(error)
    else:
        points.main(conn, name, file, layer, segment, snap)
        voronoi.main(conn, name, file, layer)
