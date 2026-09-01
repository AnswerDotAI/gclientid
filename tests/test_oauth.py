import asyncio, json, pytest
from urllib.parse import parse_qs, urlparse

from gclientid.oauth import LOCAL_REDIRECT_URI, REMOTE_REDIRECT_URI, auth_url, finish_auth, _auth_request, _callback_code, _matching_refresh


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


def test_split_auth(tmp_path):
    client_path = tmp_path/'oauth-client.json'
    token_path = tmp_path/'oauth-token.json'
    client = dict(client_id='client', client_secret='secret', token_uri='https://example.com/token',
        redirect_uris=[LOCAL_REDIRECT_URI, REMOTE_REDIRECT_URI])
    client_path.write_text(json.dumps(dict(web=client)))

    url = auth_url(client_path, token_path, preset=None, scopes=['scope'], account='me@example.com')
    query = parse_qs(urlparse(url).query)
    assert query['redirect_uri'] == [REMOTE_REDIRECT_URI]
    assert query['login_hint'] == ['me@example.com']
    assert query['prompt'] == ['consent']
    assert query['scope'] == ['scope']
    with pytest.raises(RuntimeError, match='state did not match'):
        asyncio.run(finish_auth('code=abc&state=wrong'))


def test_matching_refresh():
    client = {'client_id': 'client'}
    saved = dict(client_id='client', account='me@example.com', refresh_token='refresh', scopes=['a', 'b'])
    assert _matching_refresh(saved, client, ['a'], 'me@example.com') == 'refresh'
    assert _matching_refresh(saved, client, ['a'], None) == 'refresh'
    assert not _matching_refresh(saved, client, ['missing'], 'me@example.com')
    assert not _matching_refresh(saved, {'client_id': 'other'}, ['a'], 'me@example.com')
    assert not _matching_refresh(saved, client, ['a'], 'other@example.com')
    assert not _matching_refresh(saved, client, ['a'], 'me')
