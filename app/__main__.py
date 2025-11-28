from multiprocessing import Pool
from pathlib import Path
from venv import logger

from . import attempt, cleanup, inputs, lines, merge, outputs
from .utils import apply_funcs, config, get_gpkg_layers, is_polygon, user

cwd = Path(__file__).parent
input_dir = cwd / "../inputs"
output_dir = cwd / "../outputs"
funcs = [inputs.main, lines.main, attempt.main, merge.main, outputs.main, cleanup.main]


def main():
    results = []
    pool = Pool(int(config["processes"]))
    for file in sorted(input_dir.iterdir()):
        if (output_dir / file.name).exists():
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


if __name__ == "__main__":
    logger.info(
        f"segment={config['segment']}, "
        f"snap={config['snap']}, "
        f"retry={config['retry']}, "
        f"verbose={config['verbose']}, "
        f"processes={config['processes']}",
    )
    for file_name in user:
        segment, snap = user[file_name].split(",")
        segment_txt = f", segment={segment}" if segment != "" else ""
        snap_txt = f", snap={snap}" if snap != "" else ""
        logger.info(f"name={file_name}{segment_txt}{snap_txt}")
    main()
