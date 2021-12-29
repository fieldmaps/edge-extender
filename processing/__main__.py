from pathlib import Path
from multiprocessing import Pool
from . import inputs, overlap, lines, points, voronoi, merge, outputs, cleanup
from .utils import logging, apply_funcs, get_gpkg_layers, is_polygon, config

logger = logging.getLogger(__name__)

cwd = Path(__file__).parent
files = cwd / '../inputs'
funcs = [inputs.main, overlap.main, lines.main, points.main, voronoi.main,
         merge.main, outputs.main, cleanup.main]

if __name__ == '__main__':
    logger.info(
        f"segment={config['segment']}, snap={config['snap']}")
    results = []
    pool = Pool()
    for file in sorted(files.iterdir(), key=lambda x: x.stat().st_size, reverse=True):
        if file.is_file() and file.suffix in ['.shp', '.geojson'] and is_polygon(file):
            args = [file.name.replace('.', '_'), file, file.stem, *funcs]
            result = pool.apply_async(apply_funcs, args=args)
            results.append(result)
        if file.is_file() and file.suffix == '.gpkg':
            for layer in get_gpkg_layers(file):
                args = [f"{file.name.replace('.', '_')}_{layer}",
                        file, layer, *funcs]
                result = pool.apply_async(apply_funcs, args=args)
                results.append(result)
    pool.close()
    pool.join()
    for result in results:
        result.get()
