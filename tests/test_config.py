import os
import pytest

def _load_config_with_env(env_vars: dict):
    import importlib
    original = {}
    for k, v in env_vars.items():
        original[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        from src.config import get_config
        return get_config()
    finally:
        for k, orig_v in original.items():
            if orig_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = orig_v
VALID_ENV = {'DB_HOST': 'localhost', 'DB_PORT': '5432', 'DB_NAME': 'chronoledger', 'DB_USER': 'testuser', 'DB_PASSWORD': 'testpass'}

def test_config_loads_valid_env():
    cfg = _load_config_with_env(VALID_ENV)
    assert cfg.db_host == 'localhost'
    assert cfg.db_port == 5432
    assert cfg.db_name == 'chronoledger'
    assert cfg.db_user == 'testuser'
    assert cfg.db_password == 'testpass'

def test_config_dsn_format():
    cfg = _load_config_with_env(VALID_ENV)
    dsn = cfg.dsn
    assert 'host=localhost' in dsn
    assert 'port=5432' in dsn
    assert 'dbname=chronoledger' in dsn
    assert 'user=testuser' in dsn
    assert 'password=testpass' in dsn

def test_config_missing_variable_raises():
    env = {k: v for k, v in VALID_ENV.items() if k != 'DB_PASSWORD'}
    saved = os.environ.pop('DB_PASSWORD', None)
    try:
        with pytest.raises(EnvironmentError, match='DB_PASSWORD'):
            _load_config_with_env(env)
    finally:
        if saved:
            os.environ['DB_PASSWORD'] = saved

def test_config_invalid_port_raises():
    env = {**VALID_ENV, 'DB_PORT': 'not_a_number'}
    with pytest.raises(ValueError, match='DB_PORT'):
        _load_config_with_env(env)

def test_config_is_immutable():
    cfg = _load_config_with_env(VALID_ENV)
    with pytest.raises((AttributeError, TypeError)):
        cfg.db_host = 'something_else'

def test_config_default_log_level():
    env = dict(VALID_ENV)
    saved = os.environ.pop('LOG_LEVEL', None)
    try:
        cfg = _load_config_with_env(env)
        assert cfg.log_level == 'INFO'
    finally:
        if saved:
            os.environ['LOG_LEVEL'] = saved

def test_config_default_schema():
    env = dict(VALID_ENV)
    saved = os.environ.pop('PIPELINE_SCHEMA', None)
    try:
        cfg = _load_config_with_env(env)
        assert cfg.pipeline_schema == 'public'
    finally:
        if saved:
            os.environ['PIPELINE_SCHEMA'] = saved
