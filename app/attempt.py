from decimal import Decimal
from venv import logger

from . import points, voronoi
from .utils import config, get_config


def main(conn, name, file, layer, *_):
    segment = get_config(name)["segment"]
    snap = get_config(name)["snap"]
    if config["retry"].lower() in ("yes", "on", "true", "1"):
        for z in range(9):
            segment_1 = Decimal(segment) * (z + 1)
            try:
                points.main(conn, name, file, layer, segment_1, snap)
                voronoi.main(conn, name, file, layer)
                if str(segment_1) != segment or str(snap) != snap:
                    logger.info(f"success: {name} segment={segment_1} snap={snap}")
                return
            except Exception:
                if config["verbose"].lower() in ("yes", "on", "true", "1"):
                    logger.info(f"fail: {name} segment={segment_1} snap={snap}")
                error = (
                    f"{name} did not succeed from segment={segment}-{segment_1} with "
                    f"snap={snap}"
                )
                logger.error(error)
                raise RuntimeError(error)
    else:
        points.main(conn, name, file, layer, segment, snap)
        voronoi.main(conn, name, file, layer)
