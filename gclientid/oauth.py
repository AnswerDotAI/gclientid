import asyncio, base64, hashlib, json, os, secrets, webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx2
from fastcdp import CDP, Page
from fastcore.basics import listify


GMAIL_SCOPE = 'https://mail.google.com/'
AUTH_SCOPE = 'https://www.googleapis.com/auth/'
def _auth_scopes(names): return tuple(f'{AUTH_SCOPE}{o}' for o in names.split())
def _apis(names): return tuple(f'{o}.googleapis.com' for o in names.split())


class Preset:
    "OAuth scopes and the Google APIs they need; `+` unions two presets in order"
    def __init__(self, scopes=(), apis=()): self.scopes,self.apis = tuple(dict.fromkeys(scopes)),tuple(dict.fromkeys(apis))
    def __add__(self, o): return Preset(self.scopes + o.scopes, self.apis + o.apis)
    def __repr__(self): return f'Preset(scopes={len(self.scopes)}, apis={len(self.apis)})'


IDENTITY = Preset(('openid', *_auth_scopes('userinfo.email userinfo.profile')))
GMAIL = IDENTITY + Preset((GMAIL_SCOPE,), _apis('gmail'))
GOOGLE_APPS = GMAIL + Preset(_auth_scopes('drive calendar contacts contacts.other.readonly directory.readonly tasks'),
    _apis('drive calendar-json people tasks docs sheets slides'))
CLOUD = Preset(_auth_scopes('cloud-platform'), _apis('cloudresourcemanager serviceusage iam'))
WORKSPACE_ADDON = IDENTITY + CLOUD + Preset(apis=_apis('gsuiteaddons'))
WORKSPACE_ADMIN = Preset(_auth_scopes('admin.directory.user admin.directory.group admin.directory.orgunit admin.directory.domain '
    'admin.directory.resource.calendar admin.directory.rolemanagement admin.reports.audit.readonly admin.reports.usage.readonly apps.licensing'),
    _apis('admin licensing'))
MAX = GOOGLE_APPS + CLOUD + WORKSPACE_ADMIN
PRESETS = {'gmail': GMAIL, 'workspace-addon': WORKSPACE_ADDON, 'google-apps': GOOGLE_APPS, 'developer': GOOGLE_APPS + CLOUD,
    'workspace-admin': GOOGLE_APPS + WORKSPACE_ADMIN, 'max': MAX}


def oauth_config(preset:str='google-apps', scopes=None, apis=None) -> Preset:
    "The preset's scopes and APIs plus any additions, deduplicated"
    if preset not in PRESETS: raise ValueError(f'Unknown preset {preset!r}; choose from {", ".join(PRESETS)}')
    return PRESETS[preset] + Preset(listify(scopes), listify(apis))


HOME_URL = 'https://answerdotai.github.io/gclientid/'
PRIVACY_URL = f'{HOME_URL}privacy/'
DOMAIN = 'answerdotai.github.io'
AUTH_URI = 'https://accounts.google.com/o/oauth2/auth'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
CERT_URI = 'https://www.googleapis.com/oauth2/v1/certs'
LOCAL_PORT = 53682
LOCAL_REDIRECT_URI = f'http://127.0.0.1:{LOCAL_PORT}/'
REMOTE_REDIRECT_URI = 'https://oauth.appapis.org/redirect'
DEV_PORTS = (5001, 5002, 8000)
DEV_REDIRECT_URIS = tuple(f'http://{h}:{p}/redirect' for p in DEV_PORTS for h in ('localhost', '127.0.0.1'))
REDIRECT_URIS = (LOCAL_REDIRECT_URI, REMOTE_REDIRECT_URI, *DEV_REDIRECT_URIS)
DESKTOP_REDIRECT_URIS = ('http://localhost',)
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


async def _setup_auth(page:Page, project_id:str, name:str, internal:bool, support_email:str, accept_terms:bool, timeout:int, terms_timeout:int):
    await page.goto(f'https://console.cloud.google.com/auth/overview?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('heading', 'OAuth Overview', timeout=timeout)
    start = tree.find('link', 'Get started')
    if not start: return

    await page.click(start.find_id())
    tree = await page.wait_for_ax('heading', 'App Information', timeout=timeout)
    await page.fill_text(tree.find_id('textbox', 'App name'), name)
    tree = await page.wait_for_ax('combobox', 'User support email', pred=lambda n: not n.props.get('disabled'), timeout=timeout)
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


def _domain_values(tree):
    "Values in the Branding page's authorized-domain textboxes"
    return [c.name for n in _form(tree).find_all('textbox', 'Authorized domain') for c in n.children]


async def _set_branding(page:Page, project_id:str, timeout:int):
    await page.goto(f'https://console.cloud.google.com/auth/branding?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('heading', 'Branding', timeout=timeout)
    await page.fill_text(tree.find_id('textbox', 'Application home page'), HOME_URL)
    await page.fill_text(tree.find_id('textbox', 'Application privacy policy link'), PRIVACY_URL)
    tree = await page.ax_tree()
    if DOMAIN not in _domain_values(tree):
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


def _form(tree): return tree.find('main').find('form')


async def console_account(page:Page, timeout:int=10) -> str:
    "Email of the Google account signed into the Cloud Console"
    await page.goto('https://console.cloud.google.com/welcome', timeout=timeout)
    tree = await page.wait_for_ax('button', 'Account:', timeout=timeout)
    return tree.find('button', 'Account:').name.rsplit('(', 1)[1].rstrip(')')


async def configure_app(
    page:Page, # Signed-in Google Cloud Console page
    project_id:str, # Existing Google Cloud project ID
    name:str='gclientids', # OAuth application name
    scopes=MAX.scopes, # Scopes to declare on the Data Access page
    internal:bool=False, # Restrict OAuth authorization to the Cloud project's organization?
    support_email:str=None, # Require this support/contact email in the signed-in Console session
    accept_terms:bool=False, # Accept Google's API Services terms without pausing?
    timeout:int=10, # Seconds to wait for each Console operation
    terms_timeout:int=600, # Seconds to wait while the developer handles the terms screen
):
    "Idempotently configure the project's OAuth app: audience, branding, declared scopes, and publication"
    await _setup_auth(page, project_id, name, internal, support_email, accept_terms, timeout, terms_timeout)
    await _set_branding(page, project_id, timeout)
    await _set_scopes(page, project_id, scopes, timeout)
    if not internal: await _publish(page, project_id, timeout)


def _redirect_group(tree): return tree.find('group', 'Authorized redirect URIs')
def _redirect_values(tree): return [c.name for n in _redirect_group(tree).find_all('textbox') for c in n.children]


async def _add_redirect_fields(page, tree, uris, timeout):
    "Add each of `uris` as a new redirect field on a client form, returning the fresh tree"
    n = len(_redirect_group(tree).find_all('textbox'))
    for uri in uris:
        n += 1
        await page.click(_redirect_group(tree).find_id('button', 'Add URI'))
        tree = await page.wait_for_ax('textbox', f'URIs {n} ', timeout=timeout)
        await page.fill_text(_redirect_group(tree).find_id('textbox', f'URIs {n} '), uri)
        tree = await page.ax_tree()
    return tree


def _created_client(tree):
    "The completion dialog of a created client, with the id and secret it shows"
    dialog = tree.find('dialog', 'OAuth client created')
    values = [n.name.removeprefix('Copy to clipboard: ') for n in dialog.find_all('button', 'Copy to clipboard:')]
    client_id = next((v for v in values if v.endswith('.apps.googleusercontent.com')), None)
    client_secret = next((v for v in values if v != client_id), None)
    if not client_id or not client_secret: raise RuntimeError('Google did not expose the new client credentials')
    return dialog,client_id,client_secret


def _client_config(data:dict):
    "The client dict inside Google's client JSON, and whether it is a Desktop (`installed`) client"
    desktop = 'installed' in data
    return data['installed' if desktop else 'web'],desktop


async def create_client(
    page:Page, # Signed-in Google Cloud Console page
    project_id:str, # Google Cloud project ID whose OAuth app `configure_app` has set up
    path:str|Path='oauth-client.json', # Destination for Google's client JSON
    name:str='gclientids', # OAuth client name
    desktop:bool=False, # Create a Desktop client instead of a Web client?
    redirects=REDIRECT_URIS, # Authorized redirect URIs of a Web client
    timeout:int=10, # Seconds to wait for each Console operation
) -> dict:
    "Create an OAuth client and save its client JSON, in Google's `web` or `installed` shape"
    path = Path(path)
    if path.exists(): raise FileExistsError(path)
    await page.goto(f'https://console.cloud.google.com/auth/clients/create?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('heading', 'Create OAuth client ID', timeout=timeout)
    await page.click(tree.find_id('combobox', 'Application type'))
    app_type = 'Desktop app' if desktop else 'Web application'
    tree = await page.wait_for_ax('option', app_type, timeout=timeout)
    await page.click(tree.find_id('option', app_type))
    tree = await page.wait_for_ax('textbox', 'Name', timeout=timeout)
    await page.fill_text(_form(tree).find('form').find_id('textbox', 'Name'), name)
    if not desktop: tree = await _add_redirect_fields(page, tree, redirects, timeout)
    await page.click(_form(tree).find('form').find_id('button', 'Create'))
    tree = await page.wait_for_ax('term', 'Client secret', timeout=timeout)
    dialog,client_id,client_secret = _created_client(tree)
    client = dict(client_id=client_id, project_id=project_id, auth_uri=AUTH_URI, token_uri=TOKEN_URI, auth_provider_x509_cert_url=CERT_URI,
        client_secret=client_secret, redirect_uris=list(DESKTOP_REDIRECT_URIS if desktop else redirects))
    config = {'installed' if desktop else 'web': client}
    _write_json(path, config)
    await page.click(dialog.find_id('button', 'OK'))
    return config


async def add_redirects(
    page:Page, # Signed-in Google Cloud Console page
    path:str|Path, # Stored Web client JSON
    redirects=REDIRECT_URIS, # Redirect URIs that must be registered
    timeout:int=10, # Seconds to wait for each Console operation
) -> list:
    "Register any of `redirects` the Web client lacks, in Google and in its JSON; returns the registered list"
    path = Path(path)
    data = json.loads(path.read_text())
    client,desktop = _client_config(data)
    if desktop: raise ValueError('Desktop clients accept any loopback redirect; only Web clients register URIs')
    await page.goto(f'https://console.cloud.google.com/auth/clients/{client["client_id"]}?project={client["project_id"]}', timeout=timeout)
    tree = await page.wait_for_ax('group', 'Authorized redirect URIs', timeout=timeout)
    current = _redirect_values(tree)
    missing = [u for u in redirects if u not in current]
    if missing:
        tree = await _add_redirect_fields(page, tree, missing, timeout)
        await page.click_and_wait(_form(tree).find_id('button', 'Save'), timeout=timeout)
    client['redirect_uris'] = current + missing
    _write_json(path, data)
    return client['redirect_uris']


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


def _is_loopback(uri): return urlparse(uri).hostname in ('127.0.0.1', 'localhost')


def _auth_request(client, scopes, account, redirect_uri=LOCAL_REDIRECT_URI, force_consent=False, desktop=False):
    "Create one PKCE authorization request"
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(24)
    if redirect_uri not in client['redirect_uris'] and not (desktop and _is_loopback(redirect_uri)):
        raise ValueError(f'OAuth client does not allow {redirect_uri}')
    params = dict(client_id=client['client_id'], redirect_uri=redirect_uri, response_type='code', scope=' '.join(scopes),
        access_type='offline', include_granted_scopes='true', code_challenge=challenge, code_challenge_method='S256', state=state)
    if force_consent: params['prompt'] = 'consent'
    if account and '@' in account: params['login_hint'] = account
    return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params),verifier,state,redirect_uri


async def _start_callback(port):
    "Start a one-shot loopback listener; returns the server, its port, and a future for the callback query string"
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

    try: server = await asyncio.start_server(receive, '127.0.0.1', port)
    except OSError as e: raise RuntimeError(f'Local OAuth callback port {port} is busy; retry with --remote') from e
    return server,server.sockets[0].getsockname()[1],callback


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


async def _request_token(client:dict, scopes, account:str, cdp=None, remote:bool=False, open_browser:bool=True,
    force_consent:bool=False, timeout:int=600, desktop:bool=False) -> dict:
    "Run one Google authorization and token exchange"
    if remote:
        if desktop: raise ValueError('Desktop clients cannot use the appapis remote redirect; authorize locally')
        auth_url,verifier,state,redirect_uri = _auth_request(client, scopes, account, REMOTE_REDIRECT_URI, force_consent)
        print(f'Open this URL in a browser:\n\n{auth_url}\n')
        if open_browser: webbrowser.open(auth_url)
        payload = input('Paste the result from oauth.appapis.org: ')
    else:
        server,port,callback = await _start_callback(0 if desktop else LOCAL_PORT)
        waiter = asyncio.create_task(asyncio.wait_for(callback, timeout))
        try:
            auth_url,verifier,state,redirect_uri = _auth_request(client, scopes, account, f'http://127.0.0.1:{port}/', force_consent, desktop)
            if cdp: payload,_ = await asyncio.gather(waiter, _open_cdp(cdp, auth_url, account, timeout))
            else:
                webbrowser.open(auth_url)
                payload = await waiter
        finally:
            if not waiter.done(): waiter.cancel()
            server.close()
            await server.wait_closed()
    code = _callback_code(payload, state)

    async with httpx2.AsyncClient(timeout=10) as http:
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


def _matching_refresh(previous, client, scopes, account):
    "Return a matching saved refresh token that covers the requested scopes"
    if previous.get('client_id') != client['client_id']: return
    if account and previous.get('account', '').casefold() != account.casefold(): return
    if not set(scopes).issubset(previous.get('scopes', ())): return
    return previous.get('refresh_token')


async def _reusable_refresh(previous, client, scopes, account):
    "Return a saved refresh token only after Google accepts a refresh grant"
    refresh = _matching_refresh(previous, client, scopes, account)
    if not refresh: return
    data = dict(client_id=client['client_id'], client_secret=client['client_secret'], refresh_token=refresh, grant_type='refresh_token')
    async with httpx2.AsyncClient(timeout=10) as http: response = await http.post(TOKEN_URI, data=data)
    if response.status_code == 400 and response.json().get('error') == 'invalid_grant': return
    response.raise_for_status()
    return refresh


async def authorize_google(
    client_path:str|Path='oauth-client.json', # Web or Desktop client JSON from create_client
    token_path:str|Path='oauth-token.json', # Destination for access and refresh token JSON
    preset:str='google-apps', # Scope preset
    scopes=None, # Additional OAuth scopes
    account:str=None, # Google account email hint and verification
    cdp:CDP=None, # Existing CDP connection; the default browser if omitted
    remote:bool=False, # Use appapis copy/paste instead of a local callback (Web clients only)?
    open_browser:bool=True, # Open the appapis authorization URL in the default browser?
) -> dict:
    "Authorize Google APIs and save refreshable token JSON"
    client,desktop = _client_config(json.loads(Path(client_path).read_text()))
    token_path = Path(token_path)
    previous = json.loads(token_path.read_text()) if token_path.exists() else {}
    scopes = oauth_config(preset, scopes).scopes
    account = account or previous.get('account')
    refresh = await _reusable_refresh(previous, client, scopes, account)
    token = await _request_token(client, scopes, account, cdp, remote, open_browser, force_consent=not refresh, desktop=desktop)
    if not token.get('refresh_token'):
        if not refresh: raise RuntimeError('Google did not return a refresh token after explicit consent')
        token['refresh_token'] = refresh
    token['created_at'] = datetime.now(timezone.utc).isoformat()
    token = _authorized_user(token, client)
    _write_json(token_path, token)
    return token
