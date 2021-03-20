from pathlib import Path
from multiprocessing import Pool
from . import inputs, lines, points, voronoi, merge, outputs, cleanup
from .utils import apply_func, get_gpkg_layers, is_polygon

cwd = Path(__file__).parent
files = (cwd / '../inputs').resolve()

if __name__ == '__main__':
    pool = Pool()
    results = []
    for file in sorted(files.iterdir()):
        if file.is_file() and file.suffix in ['.shp', '.geojson'] and is_polygon(file):
            args = (file.name.replace('.', '_'), file, file.stem,
                    inputs.main, lines.main, points.main, voronoi.main,
                    merge.main, outputs.main, cleanup.main)
            result = pool.apply_async(apply_func, args=args)
            results.append(result)
        if file.is_file() and file.suffix == '.gpkg':
            for layer in get_gpkg_layers(file):
                args = (f"{file.name.replace('.', '_')}_{layer}", file, layer,
                        inputs.main, lines.main, points.main, voronoi.main,
                        merge.main, outputs.main, cleanup.main)
                result = pool.apply_async(apply_func, args=args)
                results.append(result)
    for result in results:
        result.get()
    pool.close()
    pool.join()
