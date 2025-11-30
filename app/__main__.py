from multiprocessing import Pool
from venv import logger

from . import attempt, cleanup, inputs, lines, merge, outputs
from .config import (
    distance,
    input_dir,
    input_file,
    output_dir,
    overwrite,
    processes,
    verbose,
)
from .utils import apply_funcs, get_gpkg_layers, is_polygon

funcs = [inputs.main, lines.main, attempt.main, merge.main, outputs.main, cleanup.main]


def main() -> None:
    """Run main function."""
    if verbose:
        logger.info(f"distance={distance} processes={processes}")
    results = []
    pool = Pool(processes)
    files = [input_file] if input_file else sorted(input_dir.iterdir())
    for file in files:
        if overwrite and (output_dir / file.name).exists():
            continue
        if (
            file.is_file()
            and file.suffix in [".shp", ".geojson", ".parquet"]
            and is_polygon(file)
        ):
            name = file.name.replace(".", "_")
            args = [name, file, file.stem, *funcs]
            result = pool.apply_async(apply_funcs, args=args)
            results.append(result)
        if file.is_file() and file.suffix == ".gpkg":
            for layer in get_gpkg_layers(file):
                name = f"{file.name.replace('.', '_')}_{layer}"
                args = [name, file, layer, *funcs]
                result = pool.apply_async(apply_funcs, args=args)
                results.append(result)
    pool.close()
    pool.join()
    for result in results:
        result.get()
    if verbose:
        logger.info("done")


if __name__ == "__main__":
    main()
