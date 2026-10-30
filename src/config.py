import logging
import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv(override=False)

@dataclass(frozen=True)
class Config:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    log_level: str
    pipeline_schema: str

    @property
    def dsn(self) -> str:
        return f'host={self.db_host} port={self.db_port} dbname={self.db_name} user={self.db_user} password={self.db_password}'

def get_config() -> Config:
    missing = []

    def _require(key: str) -> str:
        val = os.environ.get(key)
        if val is None or val.strip() == '':
            missing.append(key)
            return ''
        return val.strip()
    db_host = _require('DB_HOST')
    db_port_raw = _require('DB_PORT')
    db_name = _require('DB_NAME')
    db_user = _require('DB_USER')
    db_password = _require('DB_PASSWORD')
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}\nCopy .env.example to .env and fill in your values.")
    try:
        db_port = int(db_port_raw)
    except ValueError:
        raise ValueError(f'DB_PORT must be an integer, got: {db_port_raw!r}')
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    pipeline_schema = os.environ.get('PIPELINE_SCHEMA', 'public')
    return Config(db_host=db_host, db_port=db_port, db_name=db_name, db_user=db_user, db_password=db_password, log_level=log_level, pipeline_schema=pipeline_schema)

def setup_logging(level: str='INFO') -> None:
    numeric_level = getattr(logging, level, logging.INFO)
    logging.basicConfig(level=numeric_level, format='%(asctime)s  %(levelname)-8s  %(name)s  %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
