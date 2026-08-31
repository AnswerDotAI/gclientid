import asyncio, time

from fastgws import GWSApi
from fastgws.auth import oauth_creds
from fastcdp import Page

from .oauth import CLOUD_SCOPES

PROJECT_ROLES = ('roles/serviceusage.serviceUsageConsumer',)
CREATE_URL = 'https://console.cloud.google.com/projectcreate'


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


async def enable_apis_ui(page:Page, project_id:str, apis, timeout:int=30):
    "Enable Google APIs through their Console pages"
    for api in apis:
        await page.goto(f'https://console.cloud.google.com/apis/library/{api}?project={project_id}', timeout=timeout)
        await page.wait_for_text(f'Service name: {api}', timeout=timeout)
        tree = await page.ax_tree()
        if enable := tree.find('button', 'enable this API'):
            await page.click(enable.find_id())
            await page.wait_for_ax('button', 'Disable API', timeout=timeout)


async def _wait_operation(api, operation, timeout=180, poll=1):
    "Wait for a Google long-running operation and return its response"
    deadline = time.monotonic() + timeout
    while not operation.get('done'):
        if time.monotonic() >= deadline: raise TimeoutError(f'Operation did not finish: {operation.name}')
        await asyncio.sleep(poll)
        operation = await api.operations.get(name=operation.name)
    if operation.get('error'): raise RuntimeError(operation.error)
    return operation.get('response')


async def cloud_clients(account):
    "Create authenticated Resource Manager and Service Usage clients"
    creds = await oauth_creds(account=account, scopes=CLOUD_SCOPES)
    return GWSApi('cloudresourcemanager', 'v3', creds=creds),GWSApi('serviceusage', 'v1', creds=creds)


async def find_organization(resource_manager, domain):
    "Find the single visible Google Cloud organization for a Workspace domain"
    result = await resource_manager.organizations.search(query=f'domain:{domain}')
    organizations = result.get('organizations', [])
    if len(organizations) != 1: raise RuntimeError(f'Expected one organization for {domain}, found {len(organizations)}')
    return organizations[0]


async def create_project(resource_manager, project_id, name=None, parent=None):
    "Create a Google Cloud project through Resource Manager"
    body = dict(project_id=project_id, display_name=name or project_id)
    if parent: body['parent'] = parent
    operation = await resource_manager.projects.create(**body)
    return await _wait_operation(resource_manager, operation)


async def find_project(resource_manager, project_id):
    "Find an accessible Cloud project by its globally unique project ID"
    result = await resource_manager.projects.search(query=f'id:{project_id}')
    matches = [p for p in result.get('projects', []) if p.get('projectId') == project_id]
    if len(matches) > 1: raise RuntimeError(f'Found multiple projects named {project_id}')
    return matches[0] if matches else None


async def enable_apis(service_usage, project, apis):
    "Enable Google APIs on a project through Service Usage"
    apis = list(dict.fromkeys(apis))
    if not apis: return
    operation = await service_usage.services.batch_enable(parent=project, service_ids=apis)
    return await _wait_operation(service_usage, operation)


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


async def grant_project_roles(resource_manager, project, member, roles=PROJECT_ROLES):
    "Idempotently grant project IAM roles to a member"
    result = await resource_manager.projects.get_iam_policy(resource=project)
    policy = dict(version=result.get('version', 1), etag=result.get('etag'), bindings=[
        dict(role=b.role, members=list(b.members)) for b in result.get('bindings', ())])
    _add_roles(policy, member, roles)
    return await resource_manager.projects.set_iam_policy(resource=project, policy=policy)


async def provision_project(account, project_id, name=None, domain=None, apis=()):
    "Create an optionally organization-owned project and enable its APIs"
    resource_manager,service_usage = await cloud_clients(account)
    parent = (await find_organization(resource_manager, domain)).name if domain else None
    project = await find_project(resource_manager, project_id)
    if project and parent and project.get('parent') != parent:
        raise RuntimeError(f'{project_id} belongs to {project.get("parent")}, not {parent}')
    if not project: project = await create_project(resource_manager, project_id, name, parent)
    await grant_project_roles(resource_manager, project.name, f'user:{account}')
    await enable_apis(service_usage, project.name, apis)
    return project


async def delete_project(account, project):
    "Soft-delete a Cloud project through Resource Manager"
    resource_manager,_ = await cloud_clients(account)
    if not str(project).startswith('projects/'):
        result = await find_project(resource_manager, project)
        if not result: raise RuntimeError(f'Project not found: {project}')
        project = result.name
    operation = await resource_manager.projects.delete(name=project)
    return await _wait_operation(resource_manager, operation)
