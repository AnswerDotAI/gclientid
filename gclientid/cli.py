import asyncio, secrets
from pathlib import Path

from fastcore.script import call_parse

from .oauth import authorize_gmail, connect_browser, create_gmail_client
from .projects import create_project


def _project_id(): return f'gclientids-{secrets.token_hex(5)}'


async def _run(project_id, name, output, account, accept_terms, cdp_chrome):
    output = Path(output).expanduser()/project_id
    client_path,token_path = output/'oauth-client.json',output/'oauth-token.json'
    existing = [p for p in (client_path, token_path) if p.exists()]
    if existing: raise FileExistsError(', '.join(map(str, existing)))

    browser = 'CDP Chrome' if cdp_chrome else 'Chrome'
    print(f'Connecting to {browser}...')
    cdp,page = await connect_browser(default_browser=not cdp_chrome)
    try:
        print(f'Creating Google Cloud project {project_id}...')
        await create_project(page, project_id, name=name, timeout=60)
        print('Creating Gmail Desktop OAuth client...')
        await create_gmail_client(page, project_id, client_path, name=name, accept_terms=accept_terms)
        print('Authorizing Gmail...')
        await authorize_gmail(cdp, client_path, token_path, account=account)
    finally:
        await page.close()
        await cdp.close()
    print(f'Project: {project_id}')
    print(f'Client: {client_path}')
    print(f'Token: {token_path}')


@call_parse
def main(
    Project:str=None, # Google Cloud project ID; a unique `gclientids-*` ID if omitted
    Name:str='gclientids', # OAuth application and Desktop client name
    Output:Path=Path('~/.config/gclientid'), # Parent directory for the project and credential files
    Account:str=None, # Google account display-name or email substring when several are signed in
    accept_terms:bool=False, # Accept Google's API Services terms automatically?
    cdp_chrome:bool=False, # Use dedicated CDP Chrome instead of normal Chrome?
):
    "Create a personal Gmail OAuth client and authorize it"
    asyncio.run(_run(Project or _project_id(), Name, Output, Account, accept_terms, cdp_chrome))
