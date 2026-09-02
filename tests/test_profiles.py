from gclientid.cli import _check_output_writable
from gclientid.config import oauth_settings, project_id


def test_project_id():
    pid = project_id('J@Answer.AI')
    assert pid == project_id('j@answer.ai') and pid.startswith('gclientids-') and len(pid) == 21
    assert project_id('j@answer.ai', internal=True) == pid + '-internal'


def test_output_writable(tmp_path):
    output = tmp_path/'new'
    _check_output_writable(output)
    assert output.is_dir() and not any(output.iterdir())
    assert oauth_settings(tmp_path, internal=True).config_file == tmp_path/'config-internal.ini'
