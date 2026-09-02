import asyncio, json, shlex
from pathlib import Path
from urllib.parse import quote, unquote

import httpx2
from fastcore.basics import ifnone
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from pyskills.core import allow

from .config import oauth_settings, output_dir


def _suffix(internal=False, desktop=False): return ('-internal' if internal else '') + ('-desktop' if desktop else '')


def client_file(
    internal:bool=False, # The Internal-audience client?
    desktop:bool=False, # The Desktop client instead of the Web client?
    output:Path=None, # Credential directory; $XDG_CONFIG_HOME/gclientid if omitted
):
    "Path of the stored OAuth client JSON"
    return output_dir(output)/f'oauth-client{_suffix(internal, desktop)}.json'


def token_file(
    account:str, # Authorized Google account email
    internal:bool=False, # Token for the Internal-audience client?
    desktop:bool=False, # Token for the Desktop client?
    output:Path=None, # Credential directory; $XDG_CONFIG_HOME/gclientid if omitted
):
    "Path of the stored authorized-user token JSON for `account`"
    return output_dir(output)/f'oauth-token-{quote(account.casefold(), safe="@._+-")}{_suffix(internal, desktop)}.json'


def token_name(token_path):
    "The `(account, internal, desktop)` a stored token's filename encodes; account is '' for a file named some other way"
    stem,flags = Path(token_path).stem,{}
    for flag in ('desktop', 'internal'):
        if stem.endswith(f'-{flag}'): stem,flags[flag] = stem.removesuffix(f'-{flag}'),True
    account = unquote(stem.removeprefix('oauth-token-')) if stem.startswith('oauth-token-') else ''
    return account,flags.get('internal', False),flags.get('desktop', False)


def reauth_cmd(token_path):
    "The `gclientid-auth` command that recreates the token stored at `token_path`"
    account,internal,desktop = token_name(token_path)
    return shlex.join(['gclientid-auth', *([account] if account else []), *(['--internal'] if internal else []), *(['--desktop'] if desktop else [])])


def _reauth_default(token_path):
    "Whether the store holding `token_path` asks for automatic re-authorization (`reauth = true` in its config)"
    account,internal,_ = token_name(token_path)
    return bool(account) and oauth_settings(Path(token_path).parent, internal=internal).get('reauth') == 'true'


async def reauthorize(token_path, scopes=None):
    "Run the stored token's `gclientid-auth` in the configured browser, adding `scopes`, and return the fresh credentials"
    from .cli import authorize_account
    path = Path(token_path)
    account,internal,desktop = token_name(path)
    if not account: raise ValueError(f'Cannot re-authorize {path}: not a gclientid token file')
    cfg = oauth_settings(path.parent, internal=internal)
    await authorize_account(account, path.parent, scopes=scopes, internal=internal, desktop=desktop, cdp_chrome=cfg.get('browser') == 'cdp-chrome')
    creds = Credentials.from_authorized_user_file(str(path))
    creds.token_path = path
    return creds


def token_has_scopes(token_path, scopes):
    "Whether the authorized-user token file at `token_path` includes all of `scopes`"
    token_path = Path(token_path).expanduser()
    if not token_path.exists(): return False
    if scopes is None: return True
    saved = set(json.loads(token_path.read_text()).get('scopes', []))
    return set(scopes).issubset(saved)


def _save_creds(creds, token_path):
    "Write `creds` back over the token file, keeping the verified `account`"
    token_path = Path(token_path).expanduser()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(token_path.read_text()) if token_path.exists() else {}
    data = {**existing, **json.loads(creds.to_json())}
    if existing.get('account'): data['account'] = existing['account']
    token_path.write_text(json.dumps(data))
    token_path.chmod(0o600)
    creds.token_path = token_path
    return creds


def _refresh_error(creds, err):
    "Explain a Google refresh failure and how to recover"
    cmd = reauth_cmd(getattr(creds, 'token_path', ''))
    if 'Reauthentication is needed' in str(err):
        account = f' for {creds.account}' if creds.account else ''
        return ValueError(f'Google Cloud session expired{account}; run `{cmd}` to reauthenticate')
    return ValueError(f'Token refresh failed; run `{cmd}` to reauthorize')


@allow
async def oauth_creds(token_path=None, scopes=None, account=None, internal=False, desktop=False, reauth=None):
    """OAuth creds from a token file, or from the stored token for `account` (`internal` and `desktop` select the client).

    `reauth` runs `gclientid-auth` in the configured browser when the token is missing, lacks `scopes`, or can no longer be
    refreshed; None follows the store's `reauth` setting.

    `@allow` is applied at definition so every imported copy is the sandbox-tracked wrapper:
    an expired token is refreshed on a worker thread, where only a tracked call's context survives the audit."""
    if account and token_path: raise ValueError('Pass either `account` or `token_path`, not both')
    if not account and not token_path: raise ValueError('Pass `account` or `token_path`')
    path = Path(token_path).expanduser() if token_path else token_file(account, internal, desktop)
    reauth = _reauth_default(path) if reauth is None else reauth

    creds = Credentials.from_authorized_user_file(str(path)) if token_has_scopes(path, scopes) else None
    if creds: creds.token_path = path
    if creds and creds.valid: return creds
    if creds and creds.expired and creds.refresh_token: return await refresh_creds(creds, reauth=reauth)
    missing = sorted(set(scopes) - set(json.loads(path.read_text()).get('scopes', []))) if scopes and path.exists() else []
    if reauth: return await reauthorize(path, scopes=missing)
    detail = f' lacks scopes {", ".join(missing)}' if missing else ' is missing or invalid'
    raise ValueError(f'Token {path}{detail}; run `{reauth_cmd(path)}` to authorize it')


async def refresh_creds(creds, token_path=None, reauth=None):
    """Refresh `creds` without blocking the event loop, saving to `token_path` (default: the file they were loaded from).

    When Google rejects the refresh, `reauth` (None: the store's setting) runs one `gclientid-auth` instead of raising."""
    token_path = ifnone(token_path, getattr(creds, 'token_path', None))
    try: await asyncio.to_thread(creds.refresh, Request())
    except RefreshError as e:
        if token_path and (_reauth_default(token_path) if reauth is None else reauth): return await reauthorize(token_path)
        raise _refresh_error(creds, e) from e
    if token_path: _save_creds(creds, token_path)
    return creds


async def logout(token_path=None, account=None, internal=False, desktop=False):
    "Revoke and remove the token selected by `account` (with `internal`/`desktop`) or `token_path`; no-op if it does not exist"
    if account and token_path: raise ValueError('Pass either `account` or `token_path`, not both')
    if not account and not token_path: raise ValueError('Pass `account` or `token_path`')
    path = Path(token_path).expanduser() if token_path else token_file(account, internal, desktop)
    if not path.exists(): return
    tok = json.loads(path.read_text())
    tok = tok.get('refresh_token') or tok.get('token')
    if tok:
        async with httpx2.AsyncClient(timeout=10) as c:
            r = await c.post('https://oauth2.googleapis.com/revoke', data={'token': tok})
            if r.status_code != 400: r.raise_for_status()
    path.unlink()
