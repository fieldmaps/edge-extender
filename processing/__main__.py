from pathlib import Path
from multiprocessing import Pool
from . import inputs, overlap, lines, points, voronoi, merge, outputs, cleanup
from .utils import (logging, apply_funcs, get_gpkg_layers,
                    is_polygon, config, user)

logger = logging.getLogger(__name__)

cwd = Path(__file__).parent
files = cwd / '../inputs'
funcs_1 = [inputs.main, overlap.main, lines.main, points.main, voronoi.main,
           merge.main, outputs.main, cleanup.main]
funcs_2 = [points.main, voronoi.main]


def run(segments, snaps, funcs):
    results = []
    pool = Pool()
    for segment in segments:
        for snap in snaps:
            for file in sorted(files.iterdir(), key=lambda x: x.stat().st_size):
                if file.is_file() and file.suffix in ['.shp', '.geojson'] and is_polygon(file):
                    args = [file.name.replace('.', '_'),
                            file, file.stem, segment, snap, *funcs]
                    result = pool.apply_async(apply_funcs, args=args)
                    results.append(result)
                if file.is_file() and file.suffix == '.gpkg':
                    for layer in get_gpkg_layers(file):
                        args = [f"{file.name.replace('.', '_')}_{layer}",
                                file, layer, segment, snap, *funcs]
                        result = pool.apply_async(apply_funcs, args=args)
                        results.append(result)
    pool.close()
    pool.join()
    for result in results:
        result.get()


if __name__ == '__main__':
    logger.info(f"default: segment={config['segment']}, " +
                f"snap={config['snap']}, validate={config['validate']}")
    for file_name in user:
        segment, snap, validate = user[file_name].split(',')
        segment_txt = f', segment={segment}' if segment != '' else ''
        snap_txt = f', snap={snap}' if snap != '' else ''
        validate_txt = f', validate={validate}' if validate != '' else ''
        logger.info(f'name={file_name}{segment_txt}{snap_txt}{validate_txt}')
    segments = config['segment'].split(',')
    snaps = config['snap'].split(',')
    if len(segments) > 1 or len(snaps) > 1:
        run(segments, snaps, funcs_2)
    else:
        run([None], [None], funcs_1)
