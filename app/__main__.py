import logging
from multiprocessing import Pool
from pathlib import Path

from . import attempt, cleanup, inputs, lines, merge, outputs, overlap, points, voronoi
from .utils import apply_funcs, config, get_gpkg_layers, is_polygon, user

logger = logging.getLogger(__name__)

cwd = Path(__file__).parent
files = cwd / "../inputs"
funcs_1 = [
    inputs.main,
    overlap.main,
    lines.main,
    attempt.main,
    merge.main,
    outputs.main,
    cleanup.main,
]
funcs_2 = [points.main, voronoi.main]


def run(processes, segments, snaps, funcs):
    results = []
    pool = Pool(processes)
    for segment in segments:
        for snap in snaps:
            for file in sorted(files.iterdir()):
                if (
                    file.is_file()
                    and file.suffix in [".shp", ".geojson", ".parquet"]
                    and is_polygon(file)
                ):
                    name = file.name.replace(".", "_")
                    args = [name, file, file.stem, segment, snap, *funcs]
                    result = pool.apply_async(apply_funcs, args=args)
                    results.append(result)
                if file.is_file() and file.suffix == ".gpkg":
                    for layer in get_gpkg_layers(file):
                        name = f"{file.name.replace('.', '_')}_{layer}"
                        args = [name, file, layer, segment, snap, *funcs]
                        result = pool.apply_async(apply_funcs, args=args)
                        results.append(result)
    pool.close()
    pool.join()
    for result in results:
        result.get()


if __name__ == "__main__":
    logger.info(
        f"segment={config['segment']}, "
        + f"snap={config['snap']}, "
        + f"validate={config['validate']}, "
        + f"retry={config['retry']}, "
        + f"verbose={config['verbose']}, "
        + f"processes={config['processes']}"
    )
    for file_name in user:
        segment, snap, validate = user[file_name].split(",")
        segment_txt = f", segment={segment}" if segment != "" else ""
        snap_txt = f", snap={snap}" if snap != "" else ""
        validate_txt = f", validate={validate}" if validate != "" else ""
        logger.info(f"name={file_name}{segment_txt}{snap_txt}{validate_txt}")
    segments = config["segment"].split(",")
    snaps = config["snap"].split(",")
    if len(segments) > 1 or len(snaps) > 1:
        run(int(config["processes"]), segments, snaps, funcs_2)
    else:
        run(int(config["processes"]), [None], [None], funcs_1)
