from gclientid.projects import _add_roles


def test_add_roles():
    policy = dict(etag='etag', bindings=[dict(role='roles/existing', members=['user:j@answer.ai'])])
    assert _add_roles(policy, 'user:j@answer.ai', ['roles/existing', 'roles/new']) is policy
    assert policy['bindings'] == [
        dict(role='roles/existing', members=['user:j@answer.ai']),
        dict(role='roles/new', members=['user:j@answer.ai'])]
    _add_roles(policy, 'user:j@answer.ai', ['roles/new'])
    assert policy['bindings'][1]['members'] == ['user:j@answer.ai']
