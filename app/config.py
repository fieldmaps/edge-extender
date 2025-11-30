from argparse import ArgumentParser
from decimal import Decimal
from logging import INFO, basicConfig
from multiprocessing import cpu_count
from os import environ, getenv
from pathlib import Path

from dotenv import load_dotenv


def is_bool(string: str) -> bool:
    """Check if string is boolean-like."""
    return string.upper() in ("YES", "ON", "TRUE", "1")


load_dotenv(override=True)
basicConfig(level=INFO, format="%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

environ["OGR_GEOJSON_MAX_OBJ_SIZE"] = "0"
cwd = Path(__file__).parent

DBNAME = getenv("DBNAME", "app")
DISTANCE = getenv("DISTANCE", "0.0001")
INPUT_DIR = getenv("INPUT_DIR", str(cwd / "../inputs"))
OUTPUT_DIR = getenv("OUTPUT_DIR", str(cwd / "../outputs"))
OVERWRITE = getenv("OVERWRITE", "NO")
PROCESSES = getenv("PROCESSES", str(cpu_count()))
VERBOSE = getenv("VERBOSE", "NO")

parser = ArgumentParser(description="Extend geometry edges.")
parser.add_argument("--dbname", help="run in a different local database")
parser.add_argument("--distance", help="decimal degrees between points on a line")
parser.add_argument("--input-dir", help="input directory for files")
parser.add_argument("--input-file", help="input file")
parser.add_argument("--output-dir", help="output directory for files")
parser.add_argument("--output-file", help="output file")
parser.add_argument("--overwrite", help="whether to overwrite existing files")
parser.add_argument("--processes", help="how many processes to use in parallel")
parser.add_argument("--verbose", help="display all success and error messages")

args = parser.parse_args()

dbname = args.dbname if args.dbname else DBNAME
distance = Decimal(args.distance if args.distance else DISTANCE)
input_dir = Path(args.input_dir if args.input_dir else INPUT_DIR)
input_file = Path(args.input_file) if args.input_file else None
output_dir = Path(args.output_dir if args.output_dir else OUTPUT_DIR)
output_file = Path(args.output_file) if args.output_file else None
overwrite = is_bool(args.overwrite if args.overwrite else OVERWRITE)
processes = int(args.processes if args.processes else PROCESSES)
verbose = is_bool(args.verbose if args.verbose else VERBOSE)
