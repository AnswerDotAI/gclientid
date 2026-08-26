import secrets
from pathlib import Path
from typing import Annotated

from fastcore.script import call_parse

from .config import config_dir, oauth_settings
from .oauth import authorize_google, connect_browser, create_client
from .projects import create_project


def _project_id(): return f'gclientids-{secrets.token_hex(5)}'


def _paths(output):
    output = config_dir() if output is None else Path(output).expanduser()
    return output,output/'oauth-client.json',output/'oauth-token.json'


def _save_settings(output, project_id, name, preset, scopes, apis):
    cfg = oauth_settings(output, create=True)
    for k,v in dict(project=project_id, name=name, preset=preset,
        scopes=' '.join(scopes or ()), apis=' '.join(apis or ())).items(): cfg[k] = v
    cfg.save()
    return cfg.config_file


async def _provision(project_id, name, output, account, preset, scopes, apis, accept_terms, cdp_chrome, authorize):
    if account and not authorize: raise ValueError('--account requires --authorize')
    output,client_path,token_path = _paths(output)
    existing = [p for p in (client_path, token_path) if p.exists()]
    if existing: raise FileExistsError(', '.join(map(str, existing)))

    browser = 'CDP Chrome' if cdp_chrome else 'Chrome'
    print(f'Connecting to {browser}...')
    cdp,page = await connect_browser(default_browser=not cdp_chrome)
    try:
        print(f'Creating Google Cloud project {project_id}...')
        await create_project(page, project_id, name=name, timeout=60)
        print(f'Creating {preset} Desktop OAuth client...')
        await create_client(page, project_id, client_path, name=name, preset=preset, scopes=scopes,
            apis=apis, accept_terms=accept_terms)
        config_path = _save_settings(output, project_id, name, preset, scopes, apis)
        if authorize:
            print('Authorizing Google account...')
            token = await authorize_google(cdp, client_path, token_path, preset=preset, scopes=scopes, account=account)
    finally:
        await page.close()
        await cdp.close()
    print(f'Project: {project_id}')
    print(f'Client: {client_path}')
    print(f'Config: {config_path}')
    if authorize:
        print(f'Account: {token["account"]}')
        print(f'Token: {token_path}')


async def _authorize(output, account, preset, scopes, cdp_chrome):
    output,client_path,token_path = _paths(output)
    cfg = oauth_settings(output)
    preset = preset or cfg.get('preset', 'google-apps')
    scopes = [*(cfg.get('scopes') or []), *(scopes or [])]
    browser = 'CDP Chrome' if cdp_chrome else 'Chrome'
    print(f'Connecting to {browser}...')
    cdp,page = await connect_browser(default_browser=not cdp_chrome)
    try:
        print(f'Authorizing Google account for {preset}...')
        token = await authorize_google(cdp, client_path, token_path, preset=preset, scopes=scopes, account=account)
    finally:
        await page.close()
        await cdp.close()
    print(f'Account: {token["account"]}')
    print(f'Token: {token_path}')


@call_parse
async def main(
    Project:str=None, # Google Cloud project ID; a unique `gclientids-*` ID if omitted
    Name:str='gclientids', # OAuth application and Desktop client name
    Output:Path=None, # Credential directory; $XDG_CONFIG_HOME/gclientid if omitted
    Account:str=None, # Google data account display-name or email substring when several are signed in
    preset:str='google-apps', # Scope preset: google-apps, developer, workspace-admin, or gmail
    scope:Annotated[str, dict(action='append')]=None, # Additional OAuth scope; may be repeated
    api:Annotated[str, dict(action='append')]=None, # Additional Google API service name; may be repeated
    accept_terms:bool=False, # Accept Google's API Services terms automatically?
    cdp_chrome:bool=False, # Use dedicated CDP Chrome instead of normal Chrome?
    Authorize:bool=False, # Also authorize a Google data account after provisioning?
):
    "Create and configure a Google OAuth Desktop client"
    await _provision(Project or _project_id(), Name, Output, Account, preset, scope, api, accept_terms, cdp_chrome, Authorize)


@call_parse
async def auth(
    Output:Path=None, # Credential directory; $XDG_CONFIG_HOME/gclientid if omitted
    Account:str=None, # Google data account display-name or email substring when several are signed in
    preset:str=None, # Scope preset; defaults to the provisioned setting or google-apps
    scope:Annotated[str, dict(action='append')]=None, # Additional OAuth scope; may be repeated
    cdp_chrome:bool=False, # Use dedicated CDP Chrome instead of normal Chrome?
):
    "Authorize a Google account using an existing OAuth Desktop client"
    await _authorize(Output, Account, preset, scope, cdp_chrome)
