import asyncio, time

import httpx2
from fastcdp import Page

from .creds import oauth_creds, refresh_creds
from .oauth import CLOUD

PROJECT_ROLES = ('roles/serviceusage.serviceUsageConsumer',)
CREATE_URL = 'https://console.cloud.google.com/projectcreate'
RESOURCE_MANAGER = 'https://cloudresourcemanager.googleapis.com/v3'
SERVICE_USAGE = 'https://serviceusage.googleapis.com/v1'


async def project_exists_ui(page:Page, project_id:str, timeout:int=10):
    "Whether the signed-in Console account can open `project_id`"
    await page.goto(f'https://console.cloud.google.com/welcome?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('button', 'Hit enter to s', timeout=timeout)
    return not tree.find('button', 'No project selected')


async def create_project_ui(page:Page, project_id:str, name:str=None, timeout:int=30):
    "Create a Google Cloud project through its Console"
    await page.goto(CREATE_URL, timeout=timeout)
    tree = await page.wait_for_ax('textbox', 'Project name', timeout=timeout)
    form = tree.find('main').find('form')
    await page.fill_text(form.find_id('textbox', 'Project name'), name or project_id)
    tree = await page.wait_for_ax('button', 'Edit the project id.', timeout=timeout)
    await page.click(tree.find('main').find('form').find_id('button', 'Edit the project id.'))
    tree = await page.wait_for_ax('textbox', 'Project ID', timeout=timeout)
    await page.fill_text(tree.find('main').find('form').find_id('textbox', 'Project ID'), project_id)
    tree = await page.wait_for_ax('button', 'Create', timeout=timeout)
    await page.click(tree.find('main').find('form').find_id('button', 'Create'))
    await page.wait_for_ax('button', f'Navigate to {project_id} project', timeout=timeout)
    return project_id


async def ensure_project_ui(page:Page, project_id:str, name:str=None, timeout:int=30):
    "Create `project_id` through the Console unless it already exists"
    if not await project_exists_ui(page, project_id, timeout): await create_project_ui(page, project_id, name, timeout)
    return project_id


async def enabled_apis_ui(page:Page, project_id:str, timeout:int=30):
    "Service names enabled on `project_id`, read from the Console's APIs dashboard"
    await page.goto(f'https://console.cloud.google.com/apis/dashboard?project={project_id}', timeout=timeout)
    tree = await page.wait_for_ax('grid', 'Enabled APIs', timeout=timeout)
    urls = [n.props.get('url', '') for n in tree.find('main').find_all('link')]
    return {u.split('/apis/api/')[1].split('/')[0] for u in urls if '/apis/api/' in u}


async def enable_apis_ui(page:Page, project_id:str, apis, timeout:int=30):
    "Enable Google APIs through their Console pages, skipping those the dashboard already lists"
    enabled = await enabled_apis_ui(page, project_id, timeout)
    for api in apis:
        if api in enabled: continue
        await page.goto(f'https://console.cloud.google.com/apis/library/{api}?project={project_id}', timeout=timeout)
        await page.wait_for_text(f'Service name: {api}', timeout=timeout)
        tree = await page.ax_tree()
        if enable := tree.find('button', 'enable this API'):
            await page.click(enable.find_id())
            await page.wait_for_ax('button', 'Disable API', timeout=timeout)


async def cloud_creds(account):
    "Load the owner's stored token, which must carry Google Cloud access"
    return await oauth_creds(account=account, scopes=CLOUD.scopes)


async def _call(creds, method, url, **kwargs):
    "One authenticated Google API request, returning its JSON; Google's error body is the error message"
    if not creds.valid: await refresh_creds(creds)
    async with httpx2.AsyncClient(timeout=60) as http:
        r = await http.request(method, url, headers={'Authorization': f'Bearer {creds.token}'}, **kwargs)
    if r.is_error: raise RuntimeError(f'{method} {url}: {r.status_code} {r.text}')
    return r.json()


async def _wait_operation(creds, base, operation, timeout=180, poll=1):
    "Wait for a Google long-running operation and return its response"
    deadline = time.monotonic() + timeout
    while not operation.get('done'):
        if time.monotonic() >= deadline: raise TimeoutError(f'Operation did not finish: {operation["name"]}')
        await asyncio.sleep(poll)
        operation = await _call(creds, 'GET', f'{base}/{operation["name"]}')
    if operation.get('error'): raise RuntimeError(operation['error'])
    return operation.get('response')


async def find_organization(creds, domain):
    "Find the single visible Google Cloud organization for a Workspace domain"
    result = await _call(creds, 'GET', f'{RESOURCE_MANAGER}/organizations:search', params=dict(query=f'domain:{domain}'))
    organizations = result.get('organizations', [])
    if len(organizations) != 1: raise RuntimeError(f'Expected one organization for {domain}, found {len(organizations)}')
    return organizations[0]


async def create_project(creds, project_id, name=None, parent=None):
    "Create a Google Cloud project through Resource Manager"
    body = dict(projectId=project_id, displayName=name or project_id)
    if parent: body['parent'] = parent
    operation = await _call(creds, 'POST', f'{RESOURCE_MANAGER}/projects', json=body)
    return await _wait_operation(creds, RESOURCE_MANAGER, operation)


async def find_project(creds, project_id):
    "Find an accessible Cloud project by its globally unique project ID"
    result = await _call(creds, 'GET', f'{RESOURCE_MANAGER}/projects:search', params=dict(query=f'id:{project_id}'))
    matches = [p for p in result.get('projects', []) if p.get('projectId') == project_id]
    if len(matches) > 1: raise RuntimeError(f'Found multiple projects named {project_id}')
    return matches[0] if matches else None


async def enable_apis(creds, project, apis):
    "Enable Google APIs on a project through Service Usage (at most 20 per call, Google's batch limit)"
    apis = list(dict.fromkeys(apis))
    for i in range(0, len(apis), 20):
        operation = await _call(creds, 'POST', f'{SERVICE_USAGE}/{project}/services:batchEnable', json=dict(serviceIds=apis[i:i+20]))
        await _wait_operation(creds, SERVICE_USAGE, operation)


def _add_roles(policy, member, roles):
    "Add one member to roles in an IAM policy without duplicating bindings"
    bindings = policy.setdefault('bindings', [])
    for role in roles:
        binding = next((b for b in bindings if b.get('role') == role), None)
        if binding is None:
            binding = dict(role=role, members=[])
            bindings.append(binding)
        if member not in binding['members']: binding['members'].append(member)
    return policy


async def grant_project_roles(creds, project, member, roles=PROJECT_ROLES):
    "Idempotently grant project IAM roles to a member"
    policy = await _call(creds, 'POST', f'{RESOURCE_MANAGER}/{project}:getIamPolicy', json={})
    _add_roles(policy, member, roles)
    return await _call(creds, 'POST', f'{RESOURCE_MANAGER}/{project}:setIamPolicy', json=dict(policy=policy))


async def provision_project(account, project_id, name=None, domain=None, apis=()):
    "Create an optionally organization-owned project and enable its APIs"
    creds = await cloud_creds(account)
    parent = (await find_organization(creds, domain))['name'] if domain else None
    project = await find_project(creds, project_id)
    if project and parent and project.get('parent') != parent:
        raise RuntimeError(f'{project_id} belongs to {project.get("parent")}, not {parent}')
    if not project: project = await create_project(creds, project_id, name, parent)
    await grant_project_roles(creds, project['name'], f'user:{account}')
    await enable_apis(creds, project['name'], apis)
    return project


async def delete_project(account, project):
    "Soft-delete a Cloud project through Resource Manager"
    creds = await cloud_creds(account)
    if not str(project).startswith('projects/'):
        result = await find_project(creds, project)
        if not result: raise RuntimeError(f'Project not found: {project}')
        project = result['name']
    operation = await _call(creds, 'DELETE', f'{RESOURCE_MANAGER}/{project}')
    return await _wait_operation(creds, RESOURCE_MANAGER, operation)
