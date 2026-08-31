from pathlib import Path

from fastcore.xdg import Config, xdg_config_home


def config_dir(): return xdg_config_home()/'gclientid'


def oauth_settings(path:Path=None, create:bool=False, internal:bool=False):
    "Load gclientid's provisioning settings"
    path = config_dir() if path is None else Path(path).expanduser()
    name = 'config-internal.ini' if internal else 'config.ini'
    return Config(path, name, create={} if create else None, types=dict(scopes=str.split, apis=str.split))
