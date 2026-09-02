import pytest
from urllib.parse import parse_qs, urlparse

from gclientid.oauth import (CLOUD, DEV_REDIRECT_URIS, GOOGLE_APPS, LOCAL_REDIRECT_URI, MAX, REMOTE_REDIRECT_URI, _auth_request,
    _callback_code, _client_config, _matching_refresh, oauth_config)


def test_callback_code():
    assert _callback_code('code=abc%2F123&state=expected', 'expected') == 'abc/123'
    with pytest.raises(RuntimeError, match='state did not match'): _callback_code('code=abc&state=wrong', 'expected')
    with pytest.raises(RuntimeError, match='access_denied: No thanks'):
        _callback_code('error=access_denied&error_description=No+thanks&state=expected', 'expected')
    with pytest.raises(RuntimeError, match='exactly one'): _callback_code('code=abc&error=access_denied&state=expected', 'expected')


def test_auth_redirect():
    client = {'client_id': 'client', 'redirect_uris': [LOCAL_REDIRECT_URI, REMOTE_REDIRECT_URI]}
    url,_,_,redirect = _auth_request(client, ['scope'], 'me@example.com')
    assert redirect == LOCAL_REDIRECT_URI
    assert parse_qs(urlparse(url).query)['redirect_uri'] == [LOCAL_REDIRECT_URI]
    assert _auth_request(client, ['scope'], None, REMOTE_REDIRECT_URI)[-1] == REMOTE_REDIRECT_URI
    with pytest.raises(ValueError, match='does not allow'): _auth_request(client, ['scope'], None, 'http://localhost:1/')

    desktop = {'client_id': 'client', 'redirect_uris': ['http://localhost']}
    assert _auth_request(desktop, ['scope'], None, 'http://127.0.0.1:4321/', desktop=True)[-1] == 'http://127.0.0.1:4321/'
    with pytest.raises(ValueError, match='does not allow'): _auth_request(desktop, ['scope'], None, REMOTE_REDIRECT_URI, desktop=True)


def test_client_config():
    assert _client_config({'web': {'client_id': 'w'}}) == ({'client_id': 'w'}, False)
    assert _client_config({'installed': {'client_id': 'd'}}) == ({'client_id': 'd'}, True)


def test_presets():
    addon = oauth_config('workspace-addon')
    assert set(CLOUD.scopes) <= set(addon.scopes) and 'gsuiteaddons.googleapis.com' in addon.apis
    assert 'https://www.googleapis.com/auth/apps.licensing' in MAX.scopes and 'licensing.googleapis.com' in MAX.apis
    extra = oauth_config('gmail', scopes='https://www.googleapis.com/auth/forms.body', apis='forms.googleapis.com')
    assert extra.scopes[-1].endswith('forms.body') and extra.apis[-1] == 'forms.googleapis.com'
    assert (GOOGLE_APPS + GOOGLE_APPS).scopes == GOOGLE_APPS.scopes
    with pytest.raises(ValueError, match='Unknown preset'): oauth_config('nope')
    assert len(DEV_REDIRECT_URIS) == 6 and all(u.endswith('/redirect') for u in DEV_REDIRECT_URIS)


def test_matching_refresh():
    client = {'client_id': 'client'}
    saved = dict(client_id='client', account='me@example.com', refresh_token='refresh', scopes=['a', 'b'])
    assert _matching_refresh(saved, client, ['a'], 'me@example.com') == 'refresh'
    assert _matching_refresh(saved, client, ['a'], None) == 'refresh'
    assert not _matching_refresh(saved, client, ['missing'], 'me@example.com')
    assert not _matching_refresh(saved, {'client_id': 'other'}, ['a'], 'me@example.com')
    assert not _matching_refresh(saved, client, ['a'], 'other@example.com')
    assert not _matching_refresh(saved, client, ['a'], 'me')
