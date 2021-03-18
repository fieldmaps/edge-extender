import logging
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(name)s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

cwd = Path(__file__).parent
outputs = (cwd / '../outputs').resolve()
outputs.mkdir(exist_ok=True, parents=True)


def main(name):
    logger.info(f'Starting {name}')
    subprocess.run([
        'ogr2ogr',
        '-overwrite',
        '-nln', name,
        (outputs / f'{name}.gpkg').resolve(),
        'PG:dbname=polygon_voronoi', f'{name}_04',
    ])
    logger.info(f'Finished {name}')
