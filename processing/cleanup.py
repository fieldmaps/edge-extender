from psycopg2.sql import SQL, Identifier
from .utils import logging

logger = logging.getLogger(__name__)

drop_tmp = """
    DROP VIEW IF EXISTS {view_05};
    DROP TABLE IF EXISTS {table_attr};
    DROP TABLE IF EXISTS {table_00};
    DROP TABLE IF EXISTS {table_01};
    DROP TABLE IF EXISTS {table_02};
    DROP TABLE IF EXISTS {table_03};
    DROP TABLE IF EXISTS {table_04};
"""


def main(cur, name, *_):
    cur.execute(SQL(drop_tmp).format(
        table_attr=Identifier(f'{name}_attr'),
        table_00=Identifier(f'{name}_00'),
        table_01=Identifier(f'{name}_01'),
        table_02=Identifier(f'{name}_02'),
        table_03=Identifier(f'{name}_03'),
        table_04=Identifier(f'{name}_04'),
        view_05=Identifier(f'{name}_05'),
    ))
    logger.info(name)
