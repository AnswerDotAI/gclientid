from urllib.parse import quote

from fastcdp import Page


CREATE_URL = 'https://console.cloud.google.com/projectcreate'
SETTINGS_URL = 'https://console.cloud.google.com/iam-admin/settings'


async def _replace_text(page:Page, node_id:int, text:str):
    "Replace the contents of a text control"
    await page.fill_text(node_id, text)


async def create_project(page:Page, project_id:str, name:str=None, timeout:int=30) -> str:
    "Create a Google Cloud project and return its project ID"
    await page.goto(CREATE_URL, timeout=timeout)
    tree = await page.wait_for_ax('textbox', 'Project name', timeout=timeout)
    form = tree.find('main').find('form')
    await _replace_text(page, form.find_id('textbox', 'Project name'), name or project_id)

    tree = await page.wait_for_ax('button', 'Edit the project id.', timeout=timeout)
    form = tree.find('main').find('form')
    await page.click(form.find_id('button', 'Edit the project id.'))
    tree = await page.wait_for_ax('textbox', 'Project ID', timeout=timeout)
    form = tree.find('main').find('form')
    await _replace_text(page, form.find_id('textbox', 'Project ID'), project_id)

    tree = await page.wait_for_ax('button', 'Create', timeout=timeout)
    await page.click(tree.find('main').find('form').find_id('button', 'Create'))
    await page.wait_for_ax('button', f'Navigate to {project_id} project', timeout=timeout)
    return project_id


async def delete_project(page:Page, project_id:str, timeout:int=30) -> str:
    "Shut down a Google Cloud project and return its project ID"
    url = f'{SETTINGS_URL}?project={quote(project_id, safe="")}'
    await page.goto(url, timeout=timeout)
    tree = await page.wait_for_ax('button', 'Shut down', timeout=timeout)
    await page.click(tree.find_id('button', 'Shut down'))

    tree = await page.wait_for_ax('dialog', 'Shut down project', timeout=timeout)
    dialog = tree.find('dialog', 'Shut down project')
    await _replace_text(page, dialog.find_id('textbox', 'Project ID'), project_id)

    tree = await page.ax_tree()
    dialog = tree.find('dialog', 'Shut down project')
    await page.click(dialog.find_id('button', 'Shut down anyway'))
    await page.wait_for_ax('dialog', 'Project is pending deletion', timeout=timeout)
    return project_id
