"""Web API contracts, using isolated SQLite databases and no network."""
from collections import defaultdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domain.config import AvitoConfig, ServerConfig
from persistence import store
from persistence.ads import SQLiteDBHandler
from server import app as server_app
from server.routers import auth


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(store, 'DB_PATH', Path(tmp_path) / 'web.db')
    monkeypatch.setattr(SQLiteDBHandler, '_instance', None)
    monkeypatch.setattr(server_app, '_config', AvitoConfig(server=ServerConfig(admin_password='test-admin')))
    monkeypatch.setattr(auth, '_AUTH_ATTEMPTS', defaultdict(list))
    with TestClient(server_app.create_app()) as client:
        user = store.register('owner', 'password')
        token = store.login('owner', 'password')
        yield client, {'Authorization': f'Bearer {token}'}, user['id']


@pytest.mark.parametrize('payload', [
    {'url': '   '}, {'url': 'https://example.com/search'},
    {'url': 'https://avito.ru.example.com/search'},
    {'url': 'https://avito.ru@localhost/search'},
    {'url': 'javascript:alert(1)'}, {'url': 'https://avito.ru:bad/search'},
    {'url': 'https://avito.ru/a\nb'},
    {'min_price': -1}, {'min_price': 20, 'max_price': 10},
    {'max_price': 10**30}, {'start_date': '2026-02-30'}, {'start_date': '20261015'},
])
def test_invalid_subscription_is_rejected_for_create_and_update(web, payload):
    client, headers, user_id = web
    link = store.create_link(user_id, {'url': 'https://www.avito.ru/search'})
    body = {'url': link['url'], **payload}
    for method, path in [('post', '/api/links'), ('put', f"/api/links/{link['id']}")]:
        response = getattr(client, method)(path, headers=headers, json=body)
        assert response.status_code == 422, response.text
    assert store.list_links(user_id) == [link]


def test_subscription_normalizes_valid_input(web):
    client, headers, _ = web
    response = client.post('/api/links', headers=headers, json={
        'url': ' https://www.avito.ru/novosibirsk?q=cpu ',
        'min_price': 0, 'max_price': 100, 'start_date': '2026-10-15',
        'white_list': [' cpu ', '', 'cpu', 'AMD'],
    })
    assert response.status_code == 201, response.text
    assert response.json()['white_list'] == ['cpu', 'AMD']
    assert response.json()['url'] == 'https://www.avito.ru/novosibirsk?q=cpu'
