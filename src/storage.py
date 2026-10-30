import logging
import pathlib
from contextlib import contextmanager
from typing import Generator
import psycopg2
import psycopg2.extras
from src.config import Config
logger = logging.getLogger(__name__)
_SCHEMA_FILE = pathlib.Path(__file__).parent.parent / 'sql' / 'schema.sql'

def get_connection(cfg: Config) -> psycopg2.extensions.connection:
    logger.debug('Opening database connection to %s:%s/%s', cfg.db_host, cfg.db_port, cfg.db_name)
    conn = psycopg2.connect(cfg.dsn)
    conn.autocommit = False
    return conn

@contextmanager
def transaction(conn: psycopg2.extensions.connection) -> Generator:
    try:
        yield conn
        conn.commit()
        logger.debug('Transaction committed.')
    except Exception:
        conn.rollback()
        logger.warning('Transaction rolled back due to exception.')
        raise

def init_schema(conn: psycopg2.extensions.connection) -> None:
    if not _SCHEMA_FILE.exists():
        raise FileNotFoundError(f'Schema file not found: {_SCHEMA_FILE}')
    sql = _SCHEMA_FILE.read_text(encoding='utf-8')
    logger.info('Running schema initialisation from %s', _SCHEMA_FILE)
    with transaction(conn):
        with conn.cursor() as cur:
            cur.execute(sql)
    logger.info('Schema initialisation complete.')

def verify_connection(conn: psycopg2.extensions.connection) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT 1')
            result = cur.fetchone()
            return result == (1,)
    except Exception as exc:
        logger.error('Connection verification failed: %s', exc)
        return False

def fetch_all_dicts(conn: psycopg2.extensions.connection, sql: str, params: tuple=()) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

def execute(conn: psycopg2.extensions.connection, sql: str, params: tuple=()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount

def execute_many(conn: psycopg2.extensions.connection, sql: str, params_list: list[tuple]) -> int:
    with conn.cursor() as cur:
        cur.executemany(sql, params_list)
        return cur.rowcount
