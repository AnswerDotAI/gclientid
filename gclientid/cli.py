import tempfile
from pathlib import Path
from typing import Annotated

from fastcore.basics import listify
from fastcore.script import call_parse

from .config import oauth_settings, output_dir, project_id
from .creds import client_file, token_file
from .oauth import MAX, REDIRECT_URIS, Preset, add_redirects, authorize_google, configure_app, connect_browser, console_account, create_client
from .projects import enable_apis_ui, ensure_project_ui, provision_project


def _check_output_writable(output):
    try:
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=output): pass
    except OSError as e: raise PermissionError(f'Cannot write to output directory: {output}') from e


def _save_settings(cfg, **settings):
    for k,v in settings.items(): cfg[k] = v
    cfg.save()
    return cfg.config_file


async def _authorize_account(output, path, preset, scopes, account, cdp=None, remote=False, open_browser=True, internal=False, desktop=False):
    if not account or '@' not in account: raise ValueError('--account must be a Google account email')
    _check_output_writable(output)
    target = token_file(account, internal, desktop, output)
    token = await authorize_google(path, target, preset=preset, scopes=scopes, account=account, cdp=cdp, remote=remote, open_browser=open_browser)
    return token,target


async def _connect(cdp_chrome):
    print(f'Connecting to {"CDP Chrome" if cdp_chrome else "Chrome"}...')
    return await connect_browser(default_browser=not cdp_chrome)


async def provision(
    project:str=None, # Google Cloud project ID; the saved one, else the owner's stable `gclientids-*` ID
    name:str='gclientids', # OAuth application and client name
    output:Path=None, # Credential directory; $XDG_CONFIG_HOME/gclientid if omitted
    owner:str=None, # Existing gclientid cloud account for API provisioning; otherwise use Cloud Console
    account:str=None, # Google account email to authorize when `authorize`
    preset:str=None, # Default scope preset for later authorization; the saved one, else google-apps
    scopes=None, # Additional OAuth scopes to declare, beyond `max`
    apis=None, # Additional Google API service names to enable, beyond `max`
    redirects=None, # Additional Web client redirect URIs, beyond the defaults
    internal:bool=False, # Use the Internal-audience project and its separate *-internal credential files?
    desktop:bool=False, # Ensure the Desktop client instead of the Web client?
    accept_terms:bool=False, # Accept Google's API Services terms automatically?
    cdp_chrome:bool=False, # Use dedicated CDP Chrome instead of normal Chrome?
    authorize:bool=False, # Also authorize `account` after provisioning?
    remote:bool=False, # Authorize through appapis copy/paste instead of the local callback?
    open_browser:bool=True, # Open the appapis authorization URL in the default browser?
):
    "Ensure the project, its APIs and OAuth app, and one client exist, then optionally authorize an account"
    if account and not authorize: raise ValueError('--account requires --authorize')
    if owner and '@' not in owner: raise ValueError('--owner must be a Google account email')
    if internal and not owner: raise ValueError('--internal requires an --owner with cloud-platform access')
    if desktop and remote: raise ValueError('Desktop clients authorize locally; --remote needs the Web client')
    output = output_dir(output)
    _check_output_writable(output)
    cfg = oauth_settings(output, create=True, internal=internal)
    path = client_file(internal, desktop, output)
    preset = preset or cfg.get('preset') or 'google-apps'
    scopes = list(dict.fromkeys([*(cfg.get('scopes') or []), *listify(scopes)]))
    apis = list(dict.fromkeys([*(cfg.get('apis') or []), *listify(apis)]))
    declared = MAX + Preset(scopes, apis)
    redirects = list(dict.fromkeys([*REDIRECT_URIS, *listify(redirects)]))

    cdp,page = await _connect(cdp_chrome)
    try:
        email = owner or await console_account(page)
        project = project or cfg.get('project') or project_id(email, internal)
        if owner:
            print(f'Ensuring Google Cloud project {project} through Resource Manager...')
            await provision_project(owner, project, name=name, domain=owner.rsplit('@', 1)[1] if internal else None, apis=declared.apis)
        else:
            print(f'Ensuring Google Cloud project {project} through Cloud Console...')
            await ensure_project_ui(page, project, name=name)
            print(f'Enabling {len(declared.apis)} Google APIs through Cloud Console...')
            await enable_apis_ui(page, project, declared.apis)
        print('Configuring the OAuth app...')
        await configure_app(page, project, name, declared.scopes, internal, email, accept_terms)
        if not path.exists():
            print(f'Creating the {"Desktop" if desktop else "Web"} OAuth client...')
            await create_client(page, project, path, name=name, desktop=desktop, redirects=redirects)
        elif not desktop:
            print('Updating the Web OAuth client redirect URIs...')
            await add_redirects(page, path, redirects)
        config_path = _save_settings(cfg, project=project, name=name, preset=preset, scopes=' '.join(scopes), apis=' '.join(apis),
            audience='internal' if internal else 'external', browser='cdp-chrome' if cdp_chrome else 'chrome', reauth='true')
        if authorize and not remote:
            print('Authorizing Google account...')
            token,tpath = await _authorize_account(output, path, preset, scopes, account, cdp=cdp, internal=internal, desktop=desktop)
    finally:
        await page.close()
        await cdp.close()
    if authorize and remote:
        print('Authorizing Google account...')
        token,tpath = await _authorize_account(output, path, preset, scopes, account, remote=True, open_browser=open_browser,
            internal=internal, desktop=desktop)
    print(f'Project: {project}')
    print(f'Client: {path}')
    print(f'Config: {config_path}')
    if authorize:
        print(f'Account: {token["account"]}')
        print(f'Token: {tpath}')
    return path


async def authorize_account(
    account:str, # Google account email to authorize
    output:Path=None, # Credential directory; $XDG_CONFIG_HOME/gclientid if omitted
    preset:str=None, # Scope preset; the saved default, else google-apps
    scopes=None, # Additional OAuth scopes
    internal:bool=False, # Use the separately stored Internal OAuth client and token?
    desktop:bool=False, # Use the Desktop client and its token instead of the Web client?
    cdp_chrome:bool=False, # Use dedicated CDP Chrome instead of normal Chrome?
    remote:bool=False, # Use appapis copy/paste instead of the local callback (Web clients only)?
    open_browser:bool=True, # Open the appapis authorization URL in the default browser?
):
    "Authorize `account` with an existing OAuth client and save its token"
    output = output_dir(output)
    path = client_file(internal, desktop, output)
    cfg = oauth_settings(output, internal=internal)
    preset = preset or cfg.get('preset') or 'google-apps'
    scopes = [*(cfg.get('scopes') or []), *listify(scopes)]
    if cfg.config_file.exists(): _save_settings(cfg, browser='cdp-chrome' if cdp_chrome else 'chrome')
    print(f'Authorizing Google account for {preset}...')
    if remote:
        token,tpath = await _authorize_account(output, path, preset, scopes, account, remote=True, open_browser=open_browser,
            internal=internal, desktop=desktop)
    else:
        cdp,page = await _connect(cdp_chrome)
        try: token,tpath = await _authorize_account(output, path, preset, scopes, account, cdp=cdp, internal=internal, desktop=desktop)
        finally:
            await page.close()
            await cdp.close()
    print(f'Account: {token["account"]}')
    print(f'Token: {tpath}')
    return tpath


@call_parse
async def main(
    Project:str=None, # Google Cloud project ID; the saved one, else the owner's stable `gclientids-*` ID
    Name:str='gclientids', # OAuth application and client name
    Output:Path=None, # Credential directory; $XDG_CONFIG_HOME/gclientid if omitted
    owner:str=None, # Existing gclientid cloud account for API provisioning; otherwise use Cloud Console
    Account:str=None, # Google account email to authorize with --authorize
    preset:str=None, # Default scope preset for later authorization: google-apps, workspace-addon, developer, workspace-admin, max, or gmail
    scope:Annotated[str, dict(action='append')]=None, # Additional OAuth scope to declare; may be repeated
    api:Annotated[str, dict(action='append')]=None, # Additional Google API service name to enable; may be repeated
    redirect:Annotated[str, dict(action='append')]=None, # Additional Web client redirect URI; may be repeated
    internal:bool=False, # Use the Internal-audience project and separate *-internal credential files?
    desktop:bool=False, # Ensure the Desktop client instead of the Web client?
    accept_terms:bool=False, # Accept Google's API Services terms automatically?
    cdp_chrome:bool=False, # Use dedicated CDP Chrome instead of normal Chrome?
    authorize:bool=False, # Also authorize a Google account after provisioning?
    remote:bool=False, # Authorize through appapis copy/paste instead of the local callback?
    open_browser:bool=True, # Open the appapis authorization URL in the default browser?
):
    "Ensure a Google Cloud project, its OAuth app, and a Web or Desktop OAuth client"
    await provision(Project, Name, Output, owner, Account, preset, scope, api, redirect, internal, desktop, accept_terms,
        cdp_chrome, authorize, remote, open_browser)


@call_parse
async def auth(
    Account:str, # Google account email to authorize
    Output:Path=None, # Credential directory; $XDG_CONFIG_HOME/gclientid if omitted
    preset:str=None, # Scope preset; defaults to the provisioned setting or google-apps
    scope:Annotated[str, dict(action='append')]=None, # Additional OAuth scope; may be repeated
    internal:bool=False, # Use the separately stored Internal OAuth client and token?
    desktop:bool=False, # Use the Desktop client and its token instead of the Web client?
    cdp_chrome:bool=False, # Use dedicated CDP Chrome instead of normal Chrome?
    remote:bool=False, # Use appapis copy/paste instead of the local callback (Web clients only)?
    open_browser:bool=True, # Open the appapis authorization URL in the default browser?
):
    "Authorize a Google account using an existing OAuth client"
    await authorize_account(Account, Output, preset, scope, internal, desktop, cdp_chrome, remote, open_browser)
