import secrets
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastcore.script import call_parse

from .config import config_dir, oauth_settings
from .oauth import authorize_google, connect_browser, create_client, oauth_config
from .projects import create_project_ui, enable_apis_ui, provision_project


def _project_id(): return f'gclientids-{secrets.token_hex(5)}'


def _suffix(internal): return '-internal' if internal else ''


def _paths(output, internal=False):
    output = config_dir() if output is None else Path(output).expanduser()
    return output,output/f'oauth-client{_suffix(internal)}.json'


def _token_path(output, account, internal=False):
    return output/f'oauth-token-{quote(account.casefold(), safe="@._+-")}{_suffix(internal)}.json'


def _token_paths(output, internal=False): return [p for p in output.glob('oauth-token-*.json') if p.stem.endswith('-internal') == internal]


async def _authorize_account(output, client_path, preset, scopes, account, cdp=None, remote=False, open_browser=True, internal=False):
    tokens = _token_paths(output, internal)
    suffix = _suffix(internal)
    token_path = _token_path(output, account, internal) if account and '@' in account else tokens[0] if account is None and len(tokens) == 1 else output/f'oauth-token.pending{suffix}.json'
    token = await authorize_google(client_path, token_path, preset=preset, scopes=scopes, account=account,
        cdp=cdp, remote=remote, open_browser=open_browser)
    target = _token_path(output, token['account'], internal)
    if token_path != target: token_path.replace(target)
    return token,target


def _save_settings(output, project_id, name, preset, scopes, apis, internal=False):
    cfg = oauth_settings(output, create=True, internal=internal)
    for k,v in dict(project=project_id, name=name, preset=preset,
        scopes=' '.join(scopes or ()), apis=' '.join(apis or ()), audience='internal' if internal else 'external').items(): cfg[k] = v
    cfg.save()
    return cfg.config_file


async def _provision(project_id, name, output, owner, account, preset, scopes, apis, internal, accept_terms, cdp_chrome, authorize, remote, open_browser):
    if account and not authorize: raise ValueError('--account requires --authorize')
    if owner and '@' not in owner: raise ValueError('--owner must be a Google account email')
    if internal and not owner: raise ValueError('--internal requires an --owner with cloud-platform access')
    output,client_path = _paths(output, internal)
    existing = [p for p in (client_path, *_token_paths(output, internal)) if p.exists()]
    if existing: raise FileExistsError(', '.join(map(str, existing)))

    _,enabled_apis = oauth_config(preset, scopes, apis)
    if owner:
        domain = owner.rsplit('@', 1)[1] if internal else None
        print(f'Creating Google Cloud project {project_id} through Resource Manager...')
        await provision_project(owner, project_id, name=name, domain=domain, apis=enabled_apis)

    browser = 'CDP Chrome' if cdp_chrome else 'Chrome'
    print(f'Connecting to {browser}...')
    cdp,page = await connect_browser(default_browser=not cdp_chrome)
    try:
        if not owner:
            print(f'Creating Google Cloud project {project_id} through Cloud Console...')
            await create_project_ui(page, project_id, name=name)
            print(f'Enabling {len(enabled_apis)} Google APIs through Cloud Console...')
            await enable_apis_ui(page, project_id, enabled_apis)
        print(f'Creating {preset} Web OAuth client...')
        await create_client(page, project_id, client_path, name=name, preset=preset, scopes=scopes,
            apis=apis, internal=internal, support_email=owner, accept_terms=accept_terms)
        config_path = _save_settings(output, project_id, name, preset, scopes, apis, internal)
        if authorize and not remote:
            print('Authorizing Google account...')
            token,token_path = await _authorize_account(output, client_path, preset, scopes, account, cdp=cdp, internal=internal)
    finally:
        await page.close()
        await cdp.close()
    if authorize and remote:
        print('Authorizing Google account...')
        token,token_path = await _authorize_account(output, client_path, preset, scopes, account,
            remote=True, open_browser=open_browser, internal=internal)
    print(f'Project: {project_id}')
    print(f'Client: {client_path}')
    print(f'Config: {config_path}')
    if authorize:
        print(f'Account: {token["account"]}')
        print(f'Token: {token_path}')


async def _authorize(output, account, preset, scopes, cdp_chrome, remote, open_browser, internal=False):
    output,client_path = _paths(output, internal)
    cfg = oauth_settings(output, internal=internal)
    preset = preset or cfg.get('preset', 'google-apps')
    scopes = [*(cfg.get('scopes') or []), *(scopes or [])]
    print(f'Authorizing Google account for {preset}...')
    if remote:
        token,token_path = await _authorize_account(output, client_path, preset, scopes, account,
            remote=True, open_browser=open_browser, internal=internal)
    else:
        browser = 'CDP Chrome' if cdp_chrome else 'Chrome'
        print(f'Connecting to {browser}...')
        cdp,page = await connect_browser(default_browser=not cdp_chrome)
        try: token,token_path = await _authorize_account(output, client_path, preset, scopes, account, cdp=cdp, internal=internal)
        finally:
            await page.close()
            await cdp.close()
    print(f'Account: {token["account"]}')
    print(f'Token: {token_path}')


@call_parse
async def main(
    Project:str=None, # Google Cloud project ID; a unique `gclientids-*` ID if omitted
    Name:str='gclientids', # OAuth application and Web client name
    Output:Path=None, # Credential directory; $XDG_CONFIG_HOME/gclientid if omitted
    owner:str=None, # Existing gclientid cloud account for API provisioning; otherwise use Cloud Console
    Account:str=None, # Google data account display-name or email substring when several are signed in
    preset:str='google-apps', # Scope preset: google-apps, workspace-addon, developer, workspace-admin, max, or gmail
    scope:Annotated[str, dict(action='append')]=None, # Additional OAuth scope; may be repeated
    api:Annotated[str, dict(action='append')]=None, # Additional Google API service name; may be repeated
    internal:bool=False, # Create an Internal app and use separate *-internal credential files?
    accept_terms:bool=False, # Accept Google's API Services terms automatically?
    cdp_chrome:bool=False, # Use dedicated CDP Chrome instead of normal Chrome?
    authorize:bool=False, # Also authorize a Google data account after provisioning?
    remote:bool=False, # Authorize through appapis copy/paste instead of the local callback?
    open_browser:bool=True, # Open the appapis authorization URL in the default browser?
):
    "Create and configure a Google OAuth Web client"
    await _provision(Project or _project_id(), Name, Output, owner, Account, preset, scope, api,
        internal, accept_terms, cdp_chrome, authorize, remote, open_browser)


@call_parse
async def auth(
    Output:Path=None, # Credential directory; $XDG_CONFIG_HOME/gclientid if omitted
    Account:str=None, # Google data account display-name or email substring when several are signed in
    preset:str=None, # Scope preset; defaults to the provisioned setting or google-apps
    scope:Annotated[str, dict(action='append')]=None, # Additional OAuth scope; may be repeated
    internal:bool=False, # Use the separately stored Internal OAuth client and token?
    cdp_chrome:bool=False, # Use dedicated CDP Chrome instead of normal Chrome?
    remote:bool=False, # Use appapis copy/paste instead of the local callback?
    open_browser:bool=True, # Open the appapis authorization URL in the default browser?
):
    "Authorize a Google account using an existing OAuth Web client"
    await _authorize(Output, Account, preset, scope, cdp_chrome, remote, open_browser, internal)
