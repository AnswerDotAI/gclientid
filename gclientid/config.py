import hashlib
from pathlib import Path

from fastcore.xdg import Config, xdg_config_home


def config_dir(): return xdg_config_home()/'gclientid'


def output_dir(path:Path=None): return config_dir() if path is None else Path(path).expanduser()


def project_id(
    owner:str, # Email of the Google account that owns the project
    internal:bool=False, # The separate Internal-audience project?
):
    "Stable default project ID for `owner`; Google requires global uniqueness, so it hashes the email"
    return f'gclientids-{hashlib.sha256(owner.casefold().encode()).hexdigest()[:10]}{"-internal" if internal else ""}'


def oauth_settings(path:Path=None, create:bool=False, internal:bool=False):
    "Load gclientid's provisioning settings"
    name = 'config-internal.ini' if internal else 'config.ini'
    return Config(output_dir(path), name, create={} if create else None, types=dict(scopes=str.split, apis=str.split))
