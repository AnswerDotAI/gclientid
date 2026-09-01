import asyncio, base64, hashlib, json, os, secrets, webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from fastcdp import CDP, Page


GMAIL_SCOPE = 'https://mail.google.com/'
AUTH_SCOPE = 'https://www.googleapis.com/auth/'
def _auth_scopes(names): return tuple(f'{AUTH_SCOPE}{o}' for o in names.split())

IDENTITY_SCOPES = ('openid', *_auth_scopes('userinfo.email userinfo.profile'))
GOOGLE_APPS_SCOPES = (*IDENTITY_SCOPES, GMAIL_SCOPE,
    *_auth_scopes('drive calendar contacts contacts.other.readonly directory.readonly tasks'))
GOOGLE_APPS_APIS = tuple(f'{o}.googleapis.com' for o in 'gmail drive calendar-json people tasks docs sheets slides'.split())
CLOUD_SCOPES = _auth_scopes('cloud-platform')
CLOUD_APIS = tuple(f'{o}.googleapis.com' for o in 'cloudresourcemanager serviceusage iam'.split())
WORKSPACE_ADDON_APIS = (*CLOUD_APIS, 'gsuiteaddons.googleapis.com')
WORKSPACE_ADMIN_SCOPES = _auth_scopes('admin.directory.user admin.directory.group admin.directory.orgunit admin.directory.domain')
WORKSPACE_ADMIN_SCOPES += _auth_scopes(
    'admin.directory.resource.calendar admin.directory.rolemanagement admin.reports.audit.readonly admin.reports.usage.readonly apps.licensing')
WORKSPACE_ADMIN_APIS = ('admin.googleapis.com', 'licensing.googleapis.com')
MAX_SCOPES = GOOGLE_APPS_SCOPES + CLOUD_SCOPES + WORKSPACE_ADMIN_SCOPES
MAX_APIS = GOOGLE_APPS_APIS + CLOUD_APIS + WORKSPACE_ADMIN_APIS
PRESETS = {}
PRESETS['gmail'] = dict(scopes=(*IDENTITY_SCOPES, GMAIL_SCOPE), apis=('gmail.googleapis.com',))
PRESETS['workspace-addon'] = dict(scopes=(*IDENTITY_SCOPES, *CLOUD_SCOPES), apis=WORKSPACE_ADDON_APIS)
PRESETS['google-apps'] = dict(scopes=GOOGLE_APPS_SCOPES, apis=GOOGLE_APPS_APIS)
PRESETS['developer'] = dict(scopes=GOOGLE_APPS_SCOPES + CLOUD_SCOPES, apis=GOOGLE_APPS_APIS + CLOUD_APIS)
PRESETS['workspace-admin'] = dict(scopes=GOOGLE_APPS_SCOPES + WORKSPACE_ADMIN_SCOPES, apis=GOOGLE_APPS_APIS + WORKSPACE_ADMIN_APIS)
PRESETS['max'] = dict(scopes=MAX_SCOPES, apis=MAX_APIS)


def oauth_config(
    preset:str|None='google-apps', # Scope and API preset, or `None` for additions only
    scopes=None, # Additional OAuth scopes
    apis=None, # Additional Google API service names
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    "Return deduplicated scopes and APIs for a preset plus additions, or additions alone with no preset"
    if preset is not None and preset not in PRESETS: raise ValueError(f'Unknown preset {preset!r}; choose from {", ".join(PRESETS)}')
    scopes = () if scopes is None else (scopes,) if isinstance(scopes, str) else tuple(scopes)
    apis = () if apis is None else (apis,) if isinstance(apis, str) else tuple(apis)
    config = PRESETS[preset] if preset is not None else dict(scopes=(), apis=())
    return tuple(dict.fromkeys((*config['scopes'], *scopes))), tuple(dict.fromkeys((*config['apis'], *apis)))
HOME_URL = 'https://answerdotai.github.io/gclientid/'
PRIVACY_URL = f'{HOME_URL}privacy/'
DOMAIN = 'answerdotai.github.io'
AUTH_URI = 'https://accounts.google.com/o/oauth2/auth'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
CERT_URI = 'https://www.googleapis.com/oauth2/v1/certs'
LOCAL_REDIRECT_URI = 'http://127.0.0.1:53682/'
REMOTE_REDIRECT_URI = 'https://oauth.appapis.org/redirect'
REDIRECT_URIS = (LOCAL_REDIRECT_URI, REMOTE_REDIRECT_URI)
MANAGED_PROFILE_NOTICE = 'chrome://managed-user-profile-notice/'


async def connect_browser(
    default_browser:bool=True, # Use normal Chrome instead of CDP Chrome?
    timeout:int=60, # Seconds to wait for normal Chrome's approval
) -> tuple[CDP, Page]:
    "Connect to Chrome and return its connection and a new page"
    try: cdp = await (CDP.connect(timeout=timeout) if default_browser else CDP.remote())
    except FileNotFoundError: raise RuntimeError('Enable Allow remote debugging in chrome://inspect/#remote-debugging, then retry') from None
    return cdp, await cdp.new_page()


def _write_json(path:str|Path, data:dict) -> Path:
    "Write private JSON and return its path"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')
    os.chmod(path, 0o600)
    return path


def _authorized_user(token, client):
    "Convert an OAuth token response to google-auth authorized-user JSON"
    created = datetime.fromisoformat(token['created_at'])
    expiry = (created + timedelta(seconds=token['expires_in'])).astimezone(timezone.utc).replace(tzinfo=None)
    return dict(token=token['access_token'], refresh_token=token['refresh_token'], token_uri=client['token_uri'],
        client_id=client['client_id'], client_secret=client['client_secret'], scopes=token['scope'].split(),
        expiry=expiry.isoformat() + 'Z', account=token['account'])


async def _wait_saved(page, timeout, label):
    "Wait for a Console Save action to settle, raising its visible error"
    await page.wait_for(r'''(() => {
        const save = [...document.querySelectorAll('main button')].find(x => x.textContent.trim() === 'Save');
        const err = [...document.querySelectorAll('[role="dialog"]')].some(x => /error/i.test(x.textContent));
        return err || !save || save.disabled || save.getAttribute('aria-disabled') === 'true';
        })()''', timeout=timeout)
    if (await page.ax_tree()).find('dialog', 'Error dialog'): raise RuntimeError(f'Google rejected the OAuth {label} settings')


async def _wait_ax_enabled(page, role, name, timeout):
    "Wait for an AX node to exist without its disabled property, returning its fresh tree"
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        tree = await page.ax_tree()
        node = tree.find(role, name)
        if node and not node.props.get('disabled'): return tree
        await asyncio.sleep(0.2)
    raise TimeoutError(f'Timed out waiting for enabled AX node role={role!r} name={name!r}')


async def _setup_auth(page:Page, project_id:str, name:str, internal:bool, support_email:str, accept_terms:bool, timeout:int, terms_timeout:int):
    await page.goto(f'https://console.cloud.google.com/auth/overview?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('heading', 'OAuth Overview', timeout=timeout)
    start = tree.find('link', 'Get started')
    if not start: return

    await page.click(start.find_id())
    tree = await page.wait_for_ax('heading', 'App Information', timeout=timeout)
    await page.fill_text(tree.find_id('textbox', 'App name'), name)
    tree = await _wait_ax_enabled(page, 'combobox', 'User support email', timeout)
    await page.click(tree.find_id('combobox', 'User support email'))
    tree = await page.wait_for_ax('option', timeout=timeout)
    emails = [n.name for n in tree.find_all('option') if '@' in n.name]
    email = next((e for e in emails if not support_email or e.casefold() == support_email.casefold()), None)
    if not email: raise RuntimeError('Google did not offer a support email')
    await page.click(tree.find_id('option', email))

    tree = await page.ax_tree()
    await page.click(tree.find('main').find('form').find_id('button', 'Next'))
    tree = await page.wait_for_ax('heading', 'Audience, step 2 of 4, in progress', timeout=timeout)
    audience = 'Internal' if internal else 'External'
    await page.click(tree.find('main').find('form').find_id('radio', audience))
    tree = await page.ax_tree()
    await page.click(tree.find('main').find('form').find_id('button', 'Next'))

    tree = await page.wait_for_ax('heading', 'Contact Information, step 3 of 4, in progress', timeout=timeout)
    contact = tree.find('main').find('form').find_id('textbox', 'Text field for emails')
    await page.fill_text(contact, email)
    await page.input.dispatchKeyEvent(type='rawKeyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    await page.input.dispatchKeyEvent(type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    tree = await page.ax_tree()
    await page.click(tree.find('main').find('form').find_id('button', 'Next'))

    tree = await page.wait_for_ax('heading', 'Finish, step 4 of 4, in progress', timeout=timeout)
    if accept_terms:
        await page.click(tree.find('main').find('form').find_id('checkbox', 'I agree'))
        tree = await page.ax_tree()
        await page.click(tree.find('main').find('form').find_id('button', 'Continue'))
        tree = await page.wait_for_ax('button', 'Create', timeout=timeout)
        await page.click(tree.find('main').find('form').find_id('button', 'Create'))
    await page.wait_for_ax('heading', 'OAuth Overview', timeout=terms_timeout)


async def _set_branding(page:Page, project_id:str, timeout:int):
    await page.goto(f'https://console.cloud.google.com/auth/branding?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('heading', 'Branding', timeout=timeout)
    await page.fill_text(tree.find_id('textbox', 'Application home page'), HOME_URL)
    await page.fill_text(tree.find_id('textbox', 'Application privacy policy link'), PRIVACY_URL)
    tree = await page.ax_tree()
    if not tree.find(name=DOMAIN):
        domains = tree.find('main').find('form').find_all('textbox', 'Authorized domain')
        if not domains:
            await page.click(tree.find_id('button', 'Add domain'))
            tree = await page.wait_for_ax('textbox', 'Authorized domain', timeout=timeout)
            domains = tree.find('main').find('form').find_all('textbox', 'Authorized domain')
        await page.fill_text(domains[-1].find_id(), DOMAIN)
        tree = await page.ax_tree()
    await page.click(tree.find('main').find('form').find_id('button', 'Save'))
    await _wait_saved(page, timeout, 'branding')


async def _set_scopes(page:Page, project_id:str, scopes, timeout:int):
    scopes = [s for s in scopes if s.startswith('https://')]
    if not scopes: return
    await page.goto(f'https://console.cloud.google.com/auth/scopes?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('heading', 'Data Access', timeout=timeout)
    await page.click(tree.find_id('button', 'Add or remove scopes'))
    tree = await page.wait_for_ax('dialog', 'Update selected scopes', timeout=timeout)
    dialog = tree.find('dialog', 'Update selected scopes')
    await page.fill_text(dialog.find_id('textbox', 'Manually paste scopes'), '\n'.join(scopes))
    tree = await page.ax_tree()
    await page.click(tree.find('dialog', 'Update selected scopes').find_id('button', 'Add to table'))
    await page.wait_for('document.querySelector(\'[aria-label="Manually paste scopes"]\')?.value === ""', timeout=timeout)
    tree = await page.ax_tree()
    await page.click(tree.find('dialog', 'Update selected scopes').find_id('button', 'Update'))
    await page.wait_for_text('Update selected scopes', present=False, timeout=timeout)
    tree = await page.ax_tree()
    await page.click(tree.find('main').find('form').find_id('button', 'Save'))
    await _wait_saved(page, timeout, 'scope')


async def _publish(page:Page, project_id:str, timeout:int):
    await page.goto(f'https://console.cloud.google.com/auth/audience?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('heading', 'Audience', timeout=timeout)
    if tree.find(name='In production'): return
    await page.click(tree.find_id('button', 'Publish app'))
    tree = await page.wait_for_ax('alertdialog', 'Push to production?', timeout=timeout)
    await page.click(tree.find('alertdialog', 'Push to production?').find_id('button', 'Confirm'))
    await page.wait_for_ax(name='In production', timeout=timeout)


async def create_client(
    page:Page, # Signed-in Google Cloud Console page
    project_id:str, # Existing Google Cloud project ID
    path:str|Path='oauth-client.json', # Destination for Google's Web client JSON
    name:str='gclientids', # OAuth application and Web client name
    preset:str='google-apps', # Scope and API preset
    scopes=None, # Additional OAuth scopes
    apis=None, # Additional Google API service names
    internal:bool=False, # Restrict OAuth authorization to the Cloud project's organization?
    support_email:str=None, # Require this support/contact email in the signed-in Console session
    accept_terms:bool=False, # Accept Google's API Services terms without pausing?
    timeout:int=10, # Seconds to wait for each Console operation
    terms_timeout:int=600, # Seconds to wait while the developer handles the terms screen
) -> dict:
    "Configure Google OAuth, create a Web client, and save its client JSON"
    path = Path(path)
    if path.exists(): raise FileExistsError(path)
    scopes,_ = oauth_config(preset, scopes, apis)
    await _setup_auth(page, project_id, name, internal, support_email, accept_terms, timeout, terms_timeout)
    await _set_branding(page, project_id, timeout)
    await _set_scopes(page, project_id, scopes, timeout)
    if not internal: await _publish(page, project_id, timeout)

    await page.goto(f'https://console.cloud.google.com/auth/clients/create?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('heading', 'Create OAuth client ID', timeout=timeout)
    await page.click(tree.find_id('combobox', 'Application type'))
    tree = await page.wait_for_ax('option', 'Web application', timeout=timeout)
    await page.click(tree.find_id('option', 'Web application'))
    tree = await page.wait_for_ax('textbox', 'Name', timeout=timeout)
    form = tree.find('main').find('form').find('form')
    await page.fill_text(form.find_id('textbox', 'Name'), name)
    redirects = tree.find('group', 'Authorized redirect URIs')
    await page.click(redirects.find_id('button', 'Add URI'))
    tree = await page.wait_for_ax('textbox', 'URIs 1', timeout=timeout)
    redirects = tree.find('group', 'Authorized redirect URIs')
    await page.fill_text(redirects.find_id('textbox', 'URIs 1'), LOCAL_REDIRECT_URI)
    await page.click(redirects.find_id('button', 'Add URI'))
    tree = await page.wait_for_ax('textbox', 'URIs 2', timeout=timeout)
    await page.fill_text(tree.find('group', 'Authorized redirect URIs').find_id('textbox', 'URIs 2'), REMOTE_REDIRECT_URI)
    tree = await page.ax_tree()
    await page.click(tree.find('main').find('form').find('form').find_id('button', 'Create'))
    tree = await page.wait_for_ax('term', 'Client secret', timeout=timeout)
    dialog = tree.find('dialog', 'OAuth client created')
    values = [n.name.removeprefix('Copy to clipboard: ') for n in dialog.find_all('button', 'Copy to clipboard:')]
    client_id = next((v for v in values if v.endswith('.apps.googleusercontent.com')), None)
    client_secret = next((v for v in values if v != client_id), None)
    if not client_id or not client_secret: raise RuntimeError('Google did not expose the new client credentials')
    web = dict(client_id=client_id, project_id=project_id, auth_uri=AUTH_URI, token_uri=TOKEN_URI,
        auth_provider_x509_cert_url=CERT_URI, client_secret=client_secret, redirect_uris=list(REDIRECT_URIS))
    config = dict(web=web)
    _write_json(path, config)
    await page.click(dialog.find_id('button', 'OK'))
    return config


def _callback_code(payload, state):
    "Validate a copied OAuth callback payload and return its code"
    query = parse_qs(payload.strip().removeprefix('?'), keep_blank_values=True)
    if query.get('state') != [state]: raise RuntimeError('OAuth state did not match')
    has_code,has_error = 'code' in query,'error' in query
    if has_code == has_error: raise RuntimeError('OAuth callback must contain exactly one of code or error')
    if has_error:
        detail = query.get('error_description', [''])[0]
        raise RuntimeError(': '.join(x for x in (query['error'][0], detail) if x))
    return query['code'][0]


def _auth_request(client, scopes, account, redirect_uri=LOCAL_REDIRECT_URI, force_consent=False):
    "Create one PKCE authorization request"
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(24)
    if redirect_uri not in client['redirect_uris']: raise ValueError(f'OAuth client does not allow {redirect_uri}')
    params = dict(client_id=client['client_id'], redirect_uri=redirect_uri, response_type='code', scope=' '.join(scopes),
        access_type='offline', include_granted_scopes='true', code_challenge=challenge, code_challenge_method='S256', state=state)
    if force_consent: params['prompt'] = 'consent'
    if account and '@' in account: params['login_hint'] = account
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params),verifier,state,redirect_uri


async def _local_callback(timeout):
    "Listen once on the registered loopback redirect and return its query string."
    callback = asyncio.get_running_loop().create_future()

    async def receive(reader, writer):
        try:
            request = (await asyncio.wait_for(reader.readline(), 5)).decode()
            target = request.split()[1]
            await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
            query = urlparse(target).query
            if not callback.done(): callback.set_result(query)
            body = b'<h1>Authorization received</h1><p>You can close this tab.</p>'
            status = b'200 OK'
        except Exception as e:
            if not callback.done(): callback.set_exception(e)
            body,status = b'<h1>Invalid OAuth callback</h1>',b'400 Bad Request'
        headers = b'HTTP/1.1 ' + status + b'\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: ' + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n'
        writer.write(headers + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    try: server = await asyncio.start_server(receive, '127.0.0.1', 53682)
    except OSError as e: raise RuntimeError('Local OAuth callback port 53682 is busy; retry with --remote') from e
    try: return await asyncio.wait_for(callback, timeout)
    finally:
        server.close()
        await server.wait_closed()


async def _oauth_stage(page, labels, timeout):
    "Wait for one OAuth screen or the loopback redirect."
    errors = ['Access blocked:', 'Something went wrong']
    expr = f'''location.hostname === '127.0.0.1' || {json.dumps([*labels, *errors])}.some(x => document.body?.innerText?.includes(x))'''
    await page.wait_for(expr, timeout=timeout)
    if await page.eval("location.hostname === '127.0.0.1'"): return
    tree = await page.ax_tree()
    heading = tree.find('heading', errors[0]) or tree.find('heading', errors[1])
    if heading:
        detail = tree.find(name='Error 400:') or tree.find(name='Error 403:')
        raise RuntimeError(': '.join(x.name for x in (heading, detail) if x))
    return tree


async def _drive_oauth(page, account, timeout):
    "Advance each known Google OAuth screen at most once."
    labels = ['Choose an account', 'Advanced', 'Select all', 'Continue', 'Allow']
    tree = await _oauth_stage(page, labels, timeout)
    if tree and tree.find('heading', 'Choose an account'):
        accounts = [n for n in tree.find('main').find_all('link') if 'Use another account' not in n.name]
        matches = accounts if account is None else [n for n in accounts if account.casefold() in n.name.casefold()]
        if len(matches) != 1: raise ValueError(f'Choose one Google account with account=: {", ".join(n.name for n in accounts)}')
        await page.dom_click(matches[0].find_id())
        tree = await _oauth_stage(page, labels[1:], timeout)
    if tree and (advanced := tree.find('link', 'Advanced') or tree.find('button', 'Advanced')):
        await page.dom_click(advanced.find_id())
        tree = await page.wait_for_ax('link', 'unsafe', timeout=timeout)
        await page.dom_click(tree.find('link', 'unsafe').find_id())
        tree = await _oauth_stage(page, labels[2:], timeout)
    if tree and (select_all := tree.find('checkbox', 'Select all')):
        await page.dom_click(select_all.find_id())
        tree = await page.ax_tree()
    if tree and (continue_ := tree.find('button', 'Continue')):
        await page.dom_click(continue_.find_id())
        tree = await _oauth_stage(page, ['Allow'], timeout)
    if tree and (allow := tree.find('button', 'Allow')): await page.dom_click(allow.find_id())


async def _dismiss_managed_profile_notice(cdp, target_id, return_target, timeout):
    "Dismiss Chrome's offer to turn a Workspace web login into a managed browser profile."
    notice = await cdp.attach_page(target_id)
    tree = await notice.wait_for_ax('button', 'Use Chrome without an account', timeout=timeout)
    await notice.dom_click(tree.find_id('button', 'Use Chrome without an account'))
    await cdp.target.activateTarget(targetId=return_target)


async def _watch_managed_profile_notices(cdp, return_target, timeout):
    "Dismiss managed-profile notices for the duration of a CDP OAuth flow."
    seen = set()
    try:
        async with cdp.on('Target.targetCreated', 'Target.targetInfoChanged') as events:
            await cdp.target.setDiscoverTargets(discover=True)

            async def handle(info):
                if info.get('type') != 'page' or info.get('url') != MANAGED_PROFILE_NOTICE: return
                target_id = info['targetId']
                if target_id in seen: return
                seen.add(target_id)
                await _dismiss_managed_profile_notice(cdp, target_id, return_target, timeout)

            for info in await cdp('Target.getTargets'): await handle(info)
            while True: await handle((await events.get())['params']['targetInfo'])
    finally:
        try: await cdp.target.setDiscoverTargets(discover=False)
        except (RuntimeError, TimeoutError): pass


async def _open_cdp(cdp, auth_url, account, timeout):
    "Open an authorization URL in CDP Chrome and wait for its loopback redirect."
    page = await cdp.new_page()
    await cdp.target.activateTarget(targetId=page.t)
    watcher = asyncio.create_task(_watch_managed_profile_notices(cdp, page.t, timeout))

    async def drive():
        await page.page.navigate(url=auth_url)
        await _drive_oauth(page, account, timeout)
        await page.wait_for("location.hostname === '127.0.0.1'", timeout=timeout)

    flow = asyncio.create_task(drive())
    try:
        done,_ = await asyncio.wait((flow, watcher), return_when=asyncio.FIRST_COMPLETED)
        if watcher in done: await watcher
        await flow
    finally:
        for task in (flow, watcher):
            if not task.done(): task.cancel()
        for task in (flow, watcher):
            try: await task
            except asyncio.CancelledError: pass
        await page.close()


async def _exchange_code(client, code, verifier, redirect_uri, account):
    "Exchange an authorization code and verify the returned Google account"
    async with httpx.AsyncClient(timeout=10) as http:
        data = dict(client_id=client['client_id'], client_secret=client['client_secret'], code=code,
            code_verifier=verifier, redirect_uri=redirect_uri, grant_type='authorization_code')
        response = await http.post(TOKEN_URI, data=data)
        response.raise_for_status()
        token = response.json()
        userinfo = await http.get('https://openidconnect.googleapis.com/v1/userinfo',
            headers={'Authorization': f'Bearer {token["access_token"]}'})
    userinfo.raise_for_status()
    user = userinfo.json()
    token['account'] = user.get('email')
    if account and account.casefold() not in f'{user.get("name", "")} {token["account"]}'.casefold():
        raise RuntimeError(f'Google authorized {token["account"]!r}, not account={account!r}')
    return token


async def _request_token(client:dict, scopes, account:str, cdp=None, remote:bool=False, open_browser:bool=True,
    force_consent:bool=False, timeout:int=600) -> dict:
    "Run one Google authorization and token exchange"
    redirect_uri = REMOTE_REDIRECT_URI if remote else LOCAL_REDIRECT_URI
    url,verifier,state,redirect_uri = _auth_request(client, scopes, account, redirect_uri, force_consent)
    if remote:
        print(f'Open this URL in a browser:\n\n{url}\n')
        if open_browser: webbrowser.open(url)
        payload = input('Paste the result from oauth.appapis.org: ')
    else:
        callback = asyncio.create_task(_local_callback(timeout))
        try:
            if cdp: browser = asyncio.create_task(_open_cdp(cdp, url, account, timeout))
            else:
                webbrowser.open(url)
                browser = None
            if browser: payload,_ = await asyncio.gather(callback, browser)
            else: payload = await callback
        finally:
            if not callback.done(): callback.cancel()
    code = _callback_code(payload, state)
    return await _exchange_code(client, code, verifier, redirect_uri, account)


def _matching_refresh(previous, client, scopes, account):
    "Return a matching saved refresh token that covers the requested scopes"
    if previous.get('client_id') != client['client_id']: return
    if account and previous.get('account', '').casefold() != account.casefold(): return
    if not set(scopes).issubset(previous.get('scopes', ())): return
    return previous.get('refresh_token')

_pending_auth = None


def auth_url(
    client_path:str|Path='oauth-client.json', # Web client JSON from create_client
    token_path:str|Path='oauth-token.json', # Destination for access and refresh token JSON
    preset:str|None='google-apps', # Scope preset, or `None` to use only `scopes`
    scopes=None, # Additional OAuth scopes
    account:str=None, # Google account email hint and verification
):
    "Start remote Google authorization and return its URL; complete with `finish_auth`"
    global _pending_auth
    client = json.loads(Path(client_path).read_text())['web']
    token_path = Path(token_path)
    previous = json.loads(token_path.read_text()) if token_path.exists() else {}
    scopes,_ = oauth_config(preset, scopes)
    account = account or previous.get('account')
    refresh = _matching_refresh(previous, client, scopes, account)
    url,verifier,state,redirect_uri = _auth_request(
        client, scopes, account, REMOTE_REDIRECT_URI, force_consent=True)
    _pending_auth = dict(client=client, token_path=token_path, scopes=scopes, account=account,
        refresh=refresh, verifier=verifier, state=state, redirect_uri=redirect_uri)
    return url


def _save_token(token, client, token_path, refresh):
    "Save a completed OAuth token response in authorized-user format"
    if not token.get('refresh_token'):
        if not refresh: raise RuntimeError('Google did not return a refresh token after explicit consent')
        token['refresh_token'] = refresh
    token['created_at'] = datetime.now(timezone.utc).isoformat()
    token = _authorized_user(token, client)
    _write_json(token_path, token)
    return token


async def finish_auth(payload):
    "Validate a copied appapis result, exchange its code, and save the authorized-user token"
    global _pending_auth
    if _pending_auth is None: raise RuntimeError('No OAuth flow in progress; call `auth_url` first')
    pending = _pending_auth
    code = _callback_code(payload, pending['state'])
    _pending_auth = None
    token = await _exchange_code(pending['client'], code, pending['verifier'],
        pending['redirect_uri'], pending['account'])
    return _save_token(token, pending['client'], pending['token_path'], pending['refresh'])


async def _reusable_refresh(previous, client, scopes, account):
    "Return a saved refresh token only after Google accepts a refresh grant"
    refresh = _matching_refresh(previous, client, scopes, account)
    if not refresh: return
    data = dict(client_id=client['client_id'], client_secret=client['client_secret'], refresh_token=refresh, grant_type='refresh_token')
    async with httpx.AsyncClient(timeout=10) as http: response = await http.post(TOKEN_URI, data=data)
    if response.status_code == 400 and response.json().get('error') == 'invalid_grant': return
    response.raise_for_status()
    return refresh


async def authorize_google(
    client_path:str|Path='oauth-client.json', # Web client JSON from create_client
    token_path:str|Path='oauth-token.json', # Destination for access and refresh token JSON
    preset:str='google-apps', # Scope preset
    scopes=None, # Additional OAuth scopes
    account:str=None, # Google account email hint and verification
    cdp:CDP=None, # Existing CDP connection; the default browser if omitted
    remote:bool=False, # Use appapis copy/paste instead of a local callback?
    open_browser:bool=True, # Open the appapis authorization URL in the default browser?
) -> dict:
    "Authorize Google APIs and save refreshable token JSON"
    client = json.loads(Path(client_path).read_text())['web']
    token_path = Path(token_path)
    previous = json.loads(token_path.read_text()) if token_path.exists() else {}
    scopes,_ = oauth_config(preset, scopes)
    account = account or previous.get('account')
    refresh = await _reusable_refresh(previous, client, scopes, account)
    token = await _request_token(client, scopes, account, cdp, remote, open_browser, force_consent=not refresh)
    return _save_token(token, client, token_path, refresh)
