import asyncio, base64, hashlib, json, os, secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from fastcdp import CDP, Page


GMAIL_SCOPE = 'https://mail.google.com/'
HOME_URL = 'https://answerdotai.github.io/gclientid/'
PRIVACY_URL = f'{HOME_URL}privacy/'
DOMAIN = 'answerdotai.github.io'
AUTH_URI = 'https://accounts.google.com/o/oauth2/auth'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
CERT_URI = 'https://www.googleapis.com/oauth2/v1/certs'


def _write_json(path:str|Path, data:dict) -> Path:
    "Write private JSON and return its path"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')
    os.chmod(path, 0o600)
    return path


async def _enable_gmail(page:Page, project_id:str, timeout:int):
    url = f'https://console.cloud.google.com/apis/library/gmail.googleapis.com?project={project_id}'
    await page.goto(url, timeout=timeout)
    tree = await page.wait_for_ax('heading', 'Gmail API', timeout=timeout)
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


async def _set_scope(page:Page, project_id:str, timeout:int):
    await page.goto(f'https://console.cloud.google.com/auth/scopes?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('heading', 'Data Access', timeout=timeout)
    if any(GMAIL_SCOPE in n.name.replace(' ', '') for n in tree.find_all('row')): return
    await page.click(tree.find_id('button', 'Add or remove scopes'))
    tree = await page.wait_for_ax('dialog', 'Update selected scopes', timeout=timeout)
    dialog = tree.find('dialog', 'Update selected scopes')
    await page.fill_text(dialog.find_id('textbox', 'Manually paste scopes'), GMAIL_SCOPE)
    tree = await page.ax_tree()
    await page.click(tree.find('dialog', 'Update selected scopes').find_id('button', 'Add to table'))
    tree = await page.wait_for_ax('row', 'https://mail', timeout=timeout)
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


async def create_gmail_client(
    page:Page, # Signed-in Google Cloud Console page
    project_id:str, # Existing Google Cloud project ID
    path:str|Path='oauth-client.json', # Destination for Google's installed-app client JSON
    name:str='gclientids', # OAuth application and Desktop client name
    accept_terms:bool=False, # Accept Google's API Services terms without pausing?
    timeout:int=60, # Seconds to wait for each Console operation
    terms_timeout:int=600, # Seconds to wait while the developer handles the terms screen
) -> dict:
    "Configure Gmail OAuth, create a Desktop client, and save its client JSON"
    path = Path(path)
    if path.exists(): raise FileExistsError(path)
    await _enable_gmail(page, project_id, timeout)
    await _setup_auth(page, project_id, name, accept_terms, timeout, terms_timeout)
    await _set_branding(page, project_id, timeout)
    await _set_scope(page, project_id, timeout)
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
    config = {'installed': {
        'client_id': client_id, 'project_id': project_id, 'auth_uri': AUTH_URI,
        'token_uri': TOKEN_URI, 'auth_provider_x509_cert_url': CERT_URI,
        'client_secret': client_secret, 'redirect_uris': ['http://localhost']}}
    _write_json(path, config)
    await page.click(dialog.find_id('button', 'OK'))
    return config


async def authorize_gmail(
    cdp:CDP, # CDP connection to a Chrome session signed into Google
    client_path:str|Path='oauth-client.json', # Installed-app client JSON from create_gmail_client
    token_path:str|Path='oauth-token.json', # Destination for access and refresh token JSON
    scope:str=GMAIL_SCOPE, # OAuth scope to request
    account:str=None, # Display-name or email substring when Google offers multiple accounts
    timeout:int=600, # Seconds to wait for browser authorization
) -> dict:
    "Authorize Gmail in Chrome and save refreshable token JSON"
    client = json.loads(Path(client_path).read_text())['installed']
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
    auth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': client['client_id'], 'redirect_uri': redirect_uri, 'response_type': 'code',
        'scope': scope, 'access_type': 'offline', 'prompt': 'consent',
        'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': state})
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
        tree = await auth_page.wait_for_ax('button', 'Allow', timeout=timeout)
        await auth_page.click(tree.find_id('button', 'Allow'))
        query = await asyncio.wait_for(callback, timeout=timeout)
    finally:
        server.close()
        await server.wait_closed()
    if query.get('state') != [state]: raise RuntimeError('OAuth state did not match')
    if 'error' in query: raise RuntimeError(query['error'][0])

    async with httpx.AsyncClient() as http:
        response = await http.post(TOKEN_URI, data={
            'client_id': client['client_id'], 'client_secret': client['client_secret'],
            'code': query['code'][0], 'code_verifier': verifier, 'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'})
    response.raise_for_status()
    token = response.json()
    token['client_id'] = client['client_id']
    token['created_at'] = datetime.now(timezone.utc).isoformat()
    _write_json(token_path, token)
    return token
