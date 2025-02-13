import logging
from decimal import Decimal

from . import points, voronoi
from .utils import config

logger = logging.getLogger(__name__)


def main(conn, name, file, layer, segment, snap, *_):
    if config["retry"].lower() in ("yes", "on", "true", "1"):
        for x in range(9):
            for y in range(9):
                for z in [1, 10]:
                    curr_segment = Decimal(config["segment"]) * (x + 1)
                    curr_snap = Decimal(config["snap"]) * (y + 1) * z
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
