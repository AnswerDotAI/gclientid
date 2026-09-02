from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from gclientid.config import config_dir, oauth_settings
from gclientid.creds import client_file, reauth_cmd, token_file, token_name, _reauth_default, _refresh_error


def test_paths(tmp_path):
    assert token_file('J@Answer.AI') == config_dir()/'oauth-token-j@answer.ai.json'
    assert token_file('j@answer.ai', internal=True, desktop=True).name == 'oauth-token-j@answer.ai-internal-desktop.json'
    assert token_file('j@answer.ai', desktop=True, output=tmp_path) == tmp_path/'oauth-token-j@answer.ai-desktop.json'
    assert client_file() == config_dir()/'oauth-client.json'
    assert client_file(internal=True, desktop=True, output=tmp_path) == tmp_path/'oauth-client-internal-desktop.json'


def test_token_name():
    assert token_name(token_file('J@Answer.AI', True, True)) == ('j@answer.ai', True, True)
    assert token_name(token_file('a+b@example.com', desktop=True)) == ('a+b@example.com', False, True)
    assert token_name('other.json') == ('', False, False)
    assert reauth_cmd(token_file('j@answer.ai', True, True)) == 'gclientid-auth j@answer.ai --internal --desktop'
    assert reauth_cmd('other.json') == 'gclientid-auth'


def test_reauth_default(tmp_path):
    path = token_file('j@answer.ai', internal=True, output=tmp_path)
    assert not _reauth_default(path)
    cfg = oauth_settings(tmp_path, create=True, internal=True)
    cfg['reauth'] = 'true'
    cfg.save()
    assert _reauth_default(path)
    assert not _reauth_default(token_file('j@answer.ai', output=tmp_path))
    assert not _reauth_default(tmp_path/'other.json')


def test_refresh_error():
    creds = Credentials(token='expired', account='j@answer.ai')
    creds.token_path = token_file('j@answer.ai', desktop=True)
    err = _refresh_error(creds, RefreshError('Reauthentication is needed.'))
    assert str(err) == 'Google Cloud session expired for j@answer.ai; run `gclientid-auth j@answer.ai --desktop` to reauthenticate'
    assert str(_refresh_error(creds, RefreshError('invalid_grant'))) == 'Token refresh failed; run `gclientid-auth j@answer.ai --desktop` to reauthorize'
