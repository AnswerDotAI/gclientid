from gclientid.cli import _paths, _check_output_writable, _token_path, _token_paths
from gclientid.config import oauth_settings
from gclientid.oauth import CLOUD_SCOPES, oauth_config


def test_internal_paths(tmp_path):
    assert _paths(tmp_path) == (tmp_path, tmp_path/'oauth-client.json')
    assert _paths(tmp_path, internal=True) == (tmp_path, tmp_path/'oauth-client-internal.json')
    assert _token_path(tmp_path, 'J@Answer.AI') == tmp_path/'oauth-token-j@answer.ai.json'
    assert _token_path(tmp_path, 'J@Answer.AI', internal=True) == tmp_path/'oauth-token-j@answer.ai-internal.json'

    normal,internal = _token_path(tmp_path, 'a@example.com'),_token_path(tmp_path, 'a@example.com', True)
    normal.touch()
    internal.touch()
    assert _token_paths(tmp_path) == [normal]
    assert _token_paths(tmp_path, internal=True) == [internal]
    assert oauth_settings(tmp_path, internal=True).config_file == tmp_path/'config-internal.ini'


def test_output_writable(tmp_path):
    output = tmp_path/'new'
    _check_output_writable(output)
    assert output.is_dir() and not any(output.iterdir())


def test_workspace_addon_preset():
    scopes,apis = oauth_config('workspace-addon')
    assert set(CLOUD_SCOPES) <= set(scopes)
    assert 'gsuiteaddons.googleapis.com' in apis
