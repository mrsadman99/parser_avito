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


@pytest.mark.parametrize('username,password', [('owner', 'password'), ('admin', 'test-admin')])
def test_sessions_persist_and_logout_revokes_only_current_session(web, username, password):
    client, _, _ = web
    def login():
        response = client.post('/api/login', json={'username': username, 'password': password})
        assert response.status_code == 200
        return response.json()['token']
    first, second = login(), login()
    store.init_db()  # startup migration must neither remove nor extend valid sessions
    with TestClient(server_app.create_app()) as another_worker:
        for token in (first, second):
            response = another_worker.get('/api/me', headers={'Authorization': f'Bearer {token}'})
            assert response.status_code == 200
            assert response.json()['is_admin'] == (username == 'admin')
    headers = {'Authorization': f'Bearer {first}'}
    assert client.post('/api/logout', headers=headers).status_code == 200
    assert client.get('/api/links', headers=headers).status_code == 401
    assert client.get('/api/me', headers={'Authorization': f'Bearer {second}'}).status_code == 200
    with store._connect() as conn:
        rows = conn.execute('SELECT token_hash FROM sessions').fetchall()
        assert all(row['token_hash'] not in (first, second) for row in rows)
        conn.execute('UPDATE sessions SET expires_at = 0')
    assert client.get('/api/me', headers={'Authorization': f'Bearer {second}'}).status_code == 401


def test_admin_password_change_invalidates_session(web, monkeypatch):
    client, _, _ = web
    token = client.post('/api/login', json={'username': 'admin', 'password': 'test-admin'}).json()['token']
    monkeypatch.setattr(auth, '_admin_password', lambda: 'changed')
    assert client.get('/api/me', headers={'Authorization': f'Bearer {token}'}).status_code == 401


def test_legacy_user_token_migrated_once(web):
    _, _, user_id = web
    with store._connect() as conn:
        conn.execute('UPDATE users SET token = ? WHERE id = ?', ('legacy-token', user_id))
    store.init_db()
    assert store.session_actor('legacy-token')['id'] == user_id
    with store._connect() as conn:
        assert conn.execute('SELECT token FROM users WHERE id = ?', (user_id,)).fetchone()[0] is None
    store.revoke_session('legacy-token')
    store.init_db()
    assert store.session_actor('legacy-token') is None


@pytest.fixture
def results(web):
    from domain.config import web_link_key
    client, headers, user_id = web
    url = 'https://www.avito.ru/search'
    link = store.create_link(user_id, {'url': url})
    other = store.register('other', 'password')
    other_link = store.create_link(other['id'], {'url': url})
    db = SQLiteDBHandler()
    with db._connect('test_seed') as conn:
        for subscription in (link, other_link):
            for i in range(1, 8):
                conn.execute('''INSERT INTO viewed
                    (id, price, source_url, source_key, city, sort_time, has_delivery, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (i, i * 100, url, web_link_key(subscription['id'], url),
                     'Новосибирск' if i % 2 else 'Москва', i * 1000, i % 2, 'large description'))
    return client, headers, link, other_link


def test_ads_page_filters_sort_and_owner_isolation(results):
    client, headers, link, other = results
    query = {'link_id': link['id'], 'page_size': 2, 'sort': 'price', 'direction': 'asc'}
    first = client.get('/api/ads/page', params=query, headers=headers).json()
    second = client.get('/api/ads/page', params={**query, 'page': 2}, headers=headers).json()
    assert first['total'] == 7
    assert [r['id'] for r in first['items']] == [1, 2]
    assert [r['id'] for r in second['items']] == [3, 4]
    assert 'description' not in first['items'][0]
    filtered = client.get('/api/ads/page', headers=headers, params={
        **query, 'city': 'НОВОСИБИРСК', 'delivery_only': True,
        'published_from': 3000, 'published_to': 5000,
    }).json()
    assert filtered['total'] == 2
    assert [r['id'] for r in filtered['items']] == [3, 5]
    assert client.get('/api/ads/page', params={'link_id': other['id']}, headers=headers).status_code == 404
    assert client.get('/api/ads/page', params=query).status_code == 401
    by_url = client.get('/api/ads/page', params={'url': link['url']}, headers=headers).json()
    assert by_url['total'] == 7
    end = client.get('/api/ads/page', params={**query, 'page': 100}, headers=headers).json()
    assert end['page'] == 4
    assert [r['id'] for r in end['items']] == [7]
    empty = client.get('/api/ads/page', params={**query, 'city': 'Missing'}, headers=headers).json()
    assert empty['total'] == 0 and empty['page'] == 1 and empty['items'] == []


@pytest.mark.parametrize('params', [
    {'page': 0}, {'page_size': 201}, {'sort': 'price; DROP TABLE viewed'},
    {'direction': 'bad'}, {'published_from': 10, 'published_to': 1},
])
def test_ads_page_rejects_invalid_query(web, params):
    client, headers, _ = web
    assert client.get('/api/ads/page', params=params, headers=headers).status_code == 422
