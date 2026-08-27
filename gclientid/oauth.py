import asyncio, base64, hashlib, json, os, secrets
from datetime import datetime, timezone
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
WORKSPACE_ADMIN_SCOPES = _auth_scopes('admin.directory.user admin.directory.group admin.directory.orgunit admin.directory.domain')
WORKSPACE_ADMIN_SCOPES += _auth_scopes(
    'admin.directory.resource.calendar admin.directory.rolemanagement admin.reports.audit.readonly admin.reports.usage.readonly')
MAX_SCOPES = GOOGLE_APPS_SCOPES + CLOUD_SCOPES + WORKSPACE_ADMIN_SCOPES
MAX_APIS = GOOGLE_APPS_APIS + CLOUD_APIS + ('admin.googleapis.com',)
PRESETS = {}
PRESETS['gmail'] = dict(scopes=(*IDENTITY_SCOPES, GMAIL_SCOPE), apis=('gmail.googleapis.com',))
PRESETS['google-apps'] = dict(scopes=GOOGLE_APPS_SCOPES, apis=GOOGLE_APPS_APIS)
PRESETS['developer'] = dict(scopes=GOOGLE_APPS_SCOPES + CLOUD_SCOPES, apis=GOOGLE_APPS_APIS + CLOUD_APIS)
PRESETS['workspace-admin'] = dict(scopes=GOOGLE_APPS_SCOPES + WORKSPACE_ADMIN_SCOPES, apis=(*GOOGLE_APPS_APIS, 'admin.googleapis.com'))
PRESETS['max'] = dict(scopes=MAX_SCOPES, apis=MAX_APIS)


def oauth_config(preset:str='google-apps', scopes=None, apis=None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    "Return the deduplicated OAuth scopes and APIs for a preset plus additions"
    if preset not in PRESETS: raise ValueError(f'Unknown preset {preset!r}; choose from {", ".join(PRESETS)}')
    scopes = () if scopes is None else (scopes,) if isinstance(scopes, str) else tuple(scopes)
    apis = () if apis is None else (apis,) if isinstance(apis, str) else tuple(apis)
    config = PRESETS[preset]
    return tuple(dict.fromkeys((*config['scopes'], *scopes))), tuple(dict.fromkeys((*config['apis'], *apis)))
HOME_URL = 'https://answerdotai.github.io/gclientid/'
PRIVACY_URL = f'{HOME_URL}privacy/'
DOMAIN = 'answerdotai.github.io'
AUTH_URI = 'https://accounts.google.com/o/oauth2/auth'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
CERT_URI = 'https://www.googleapis.com/oauth2/v1/certs'


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


async def _enable_apis(page:Page, project_id:str, apis, timeout:int):
    for api in apis:
        url = f'https://console.cloud.google.com/apis/library/{api}?project={project_id}'
        await page.goto(url, timeout=timeout)
        await page.wait_for_text(f'Service name: {api}', timeout=timeout)
        tree = await page.ax_tree()
        enable = tree.find('button', 'enable this API')
        if enable:
            await page.click(enable.find_id())
            await page.wait_for_ax('button', 'Disable API', timeout=timeout)


async def _setup_auth(page:Page, project_id:str, name:str, accept_terms:bool, timeout:int, terms_timeout:int):
    await page.goto(f'https://console.cloud.google.com/auth/overview?project={project_id}', timeout=timeout)
    tree = await page.ax_tree()
    start = tree.find('link', 'Get started')
    if not start: return

    await page.click(start.find_id())
    tree = await page.wait_for_ax('heading', 'App Information', timeout=timeout)
    await page.fill_text(tree.find_id('textbox', 'App name'), name)
    await page.wait_for(r'''[...document.querySelectorAll('[role="combobox"]')].some(
        x => x.getAttribute('aria-label') === 'User support email' && x.getAttribute('aria-disabled') !== 'true')''', timeout=timeout)
    tree = await page.ax_tree()
    await page.click(tree.find_id('combobox', 'User support email'))
    tree = await page.wait_for_ax('option', timeout=timeout)
    email = next((n.name for n in tree.find_all('option') if '@' in n.name), None)
    if not email: raise RuntimeError('Google did not offer a support email')
    await page.click(tree.find_id('option', email))

    tree = await page.ax_tree()
    await page.click(tree.find('main').find('form').find_id('button', 'Next'))
    tree = await page.wait_for_ax('heading', 'Audience, step 2 of 4, in progress', timeout=timeout)
    await page.click(tree.find('main').find('form').find_id('radio', 'External'))
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
    await page.wait_for_ready(timeout=timeout)
    if (await page.ax_tree()).find('dialog', 'Error dialog'): raise RuntimeError('Google rejected the OAuth branding settings')


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
    await page.wait_for_ready(timeout=timeout)


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
    path:str|Path='oauth-client.json', # Destination for Google's installed-app client JSON
    name:str='gclientids', # OAuth application and Desktop client name
    preset:str='google-apps', # Scope and API preset
    scopes=None, # Additional OAuth scopes
    apis=None, # Additional Google API service names
    accept_terms:bool=False, # Accept Google's API Services terms without pausing?
    timeout:int=60, # Seconds to wait for each Console operation
    terms_timeout:int=600, # Seconds to wait while the developer handles the terms screen
) -> dict:
    "Configure Google OAuth, create a Desktop client, and save its client JSON"
    path = Path(path)
    if path.exists(): raise FileExistsError(path)
    scopes,apis = oauth_config(preset, scopes, apis)
    await _enable_apis(page, project_id, apis, timeout)
    await _setup_auth(page, project_id, name, accept_terms, timeout, terms_timeout)
    await _set_branding(page, project_id, timeout)
    await _set_scopes(page, project_id, scopes, timeout)
    await _publish(page, project_id, timeout)

    await page.goto(f'https://console.cloud.google.com/auth/clients/create?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('heading', 'Create OAuth client ID', timeout=timeout)
    await page.click(tree.find_id('combobox', 'Application type'))
    tree = await page.wait_for_ax('option', 'Desktop app', timeout=timeout)
    await page.click(tree.find_id('option', 'Desktop app'))
    tree = await page.wait_for_ax('textbox', 'Name', timeout=timeout)
    form = tree.find('main').find('form').find('form')
    await page.fill_text(form.find_id('textbox', 'Name'), name)
    tree = await page.ax_tree()
    await page.click(tree.find('main').find('form').find('form').find_id('button', 'Create'))
    tree = await page.wait_for_ax('dialog', 'OAuth client created', timeout=timeout)
    dialog = tree.find('dialog', 'OAuth client created')
    values = [n.name.removeprefix('Copy to clipboard: ') for n in dialog.find_all('button', 'Copy to clipboard:')]
    client_id = next((v for v in values if v.endswith('.apps.googleusercontent.com')), None)
    client_secret = next((v for v in values if v != client_id), None)
    if not client_id or not client_secret: raise RuntimeError('Google did not expose the new client credentials')
    installed = dict(client_id=client_id, project_id=project_id, auth_uri=AUTH_URI, token_uri=TOKEN_URI,
        auth_provider_x509_cert_url=CERT_URI, client_secret=client_secret, redirect_uris=['http://localhost'])
    config = dict(installed=installed)
    _write_json(path, config)
    await page.click(dialog.find_id('button', 'OK'))
    return config


async def _request_token(cdp:CDP, client:dict, scopes, account:str, timeout:int, force_consent:bool=False) -> dict:
    "Run one Google authorization and token exchange"
    callback = asyncio.get_running_loop().create_future()

    async def receive_oauth(reader, writer):
        request = (await reader.readline()).decode()
        query = parse_qs(urlparse(request.split()[1]).query)
        while await reader.readline() not in (b'\r\n', b''): pass
        if not callback.done(): callback.set_result(query)
        body = b'<h1>Authorization received</h1><p>You can close this tab.</p>'
        headers = b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n'
        writer.write(headers + body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(receive_oauth, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(24)
    redirect_uri = f'http://127.0.0.1:{port}/'
    params = dict(client_id=client['client_id'], redirect_uri=redirect_uri, response_type='code', scope=' '.join(scopes),
        access_type='offline', include_granted_scopes='true', code_challenge=challenge, code_challenge_method='S256', state=state)
    if force_consent: params['prompt'] = 'consent'
    if account and '@' in account: params['login_hint'] = account
    auth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)
    auth_page = None
    try:
        auth_page = await cdp.new_page()
        await cdp.target.activateTarget(targetId=auth_page.t)
        await auth_page.goto(auth_url, timeout=60)
        tree = await auth_page.ax_tree()
        if tree.find('heading', 'Choose an account'):
            accounts = [n for n in tree.find('list').find_all('link') if 'Use another account' not in n.name]
            matches = accounts if account is None else [n for n in accounts if account.casefold() in n.name.casefold()]
            if len(matches) != 1:
                choices = ', '.join(n.name for n in accounts)
                raise ValueError(f'Choose one Google account with account=: {choices}')
            await auth_page.click(matches[0].find_id())
        labels = "['Advanced', 'unsafe', 'Select all', 'Continue', 'Allow']"
        consent_ready = f"location.hostname === '127.0.0.1' || {labels}.some(x => document.body?.innerText?.includes(x))"
        selected_all = False
        while not callback.done():
            await auth_page.wait_for(consent_ready, timeout=timeout)
            if callback.done(): break
            tree = await auth_page.ax_tree()
            action = tree.find('link', 'Advanced') or tree.find('link', 'unsafe')
            select_all = tree.find('checkbox', 'Select all')
            if select_all and not selected_all: action,selected_all = select_all,True
            action = action or tree.find('button', 'Continue') or tree.find('button', 'Allow')
            if not action: break
            await auth_page.click(action.find_id())
            try: await asyncio.wait_for(asyncio.shield(callback), timeout=1)
            except TimeoutError: pass
        query = await asyncio.wait_for(callback, timeout=timeout)
    finally:
        server.close()
        await server.wait_closed()
        if auth_page:
            try: await auth_page.close()
            except RuntimeError: pass
    if query.get('state') != [state]: raise RuntimeError('OAuth state did not match')
    if 'error' in query: raise RuntimeError(query['error'][0])

    async with httpx.AsyncClient() as http:
        data = dict(client_id=client['client_id'], client_secret=client['client_secret'], code=query['code'][0],
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


async def authorize_google(
    cdp:CDP, # CDP connection to a Chrome session signed into Google
    client_path:str|Path='oauth-client.json', # Installed-app client JSON from create_client
    token_path:str|Path='oauth-token.json', # Destination for access and refresh token JSON
    preset:str='google-apps', # Scope preset
    scopes=None, # Additional OAuth scopes
    account:str=None, # Display-name or email substring when Google offers multiple accounts
    timeout:int=600, # Seconds to wait for browser authorization
) -> dict:
    "Authorize Google APIs in Chrome and save refreshable token JSON"
    client = json.loads(Path(client_path).read_text())['installed']
    token_path = Path(token_path)
    previous = json.loads(token_path.read_text()) if token_path.exists() else {}
    scopes,_ = oauth_config(preset, scopes)
    token = await _request_token(cdp, client, scopes, account, timeout)
    if not token.get('refresh_token'):
        same_grant = previous.get('client_id') == client['client_id'] and previous.get('account') == token['account']
        if same_grant and previous.get('refresh_token'): token['refresh_token'] = previous['refresh_token']
        else:
            token = await _request_token(cdp, client, scopes, account, timeout, force_consent=True)
            if not token.get('refresh_token'): raise RuntimeError('Google did not return a refresh token after explicit consent')
    token['client_id'] = client['client_id']
    token['created_at'] = datetime.now(timezone.utc).isoformat()
    _write_json(token_path, token)
    return token
