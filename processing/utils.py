from configparser import ConfigParser
from pathlib import Path

cwd = Path(__file__).parent
cfg = ConfigParser()
cfg.read((cwd / '../config.ini').resolve())
config = cfg['default']


def apply_func(name, file, *args):
    for func in args:
        func(name, file)
