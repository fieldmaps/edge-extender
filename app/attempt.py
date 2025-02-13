import logging
from decimal import Decimal

from . import points, voronoi
from .utils import config

logger = logging.getLogger(__name__)


def main(conn, name, file, layer, segment, snap, *_):
    if config["retry"].lower() in ("yes", "on", "true", "1"):
        for z in range(9):
            for y in [1, 10]:
                for x in range(9):
                    curr_segment = Decimal(config["segment"]) * (z + 1)
                    curr_snap = Decimal(config["snap"]) * (x + 1) * y
                    try:
                        logger.info(f"{name} segment={curr_segment} snap={curr_snap}")
                        points.main(conn, name, file, layer, curr_segment, curr_snap)
                        voronoi.main(conn, name, file, layer, curr_segment, curr_snap)
                        return
                    except:
                        pass
    else:
        points.main(conn, name, file, layer, segment, snap)
        voronoi.main(conn, name, file, layer, segment, snap)
