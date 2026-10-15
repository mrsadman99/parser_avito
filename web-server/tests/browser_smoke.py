"""Optional browser regression: build first, then run with Python + Playwright.

All HTTP requests are intercepted; no API process or real database is used.
"""
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

DIST = Path(__file__).resolve().parents[1] / 'dist'


def main():
    state = {'links': [], 'login': [], 'save': [], 'ads': [], 'queries': [],
             'hold_ads': False, 'unauthorized': False, 'fail_ads': False, 'logout': 0}
    errors = []

    def reply(route, data, status=200):
        route.fulfill(status=status, content_type='application/json', body=json.dumps(data))

    def ads_reply(route, title=None):
        query = parse_qs(urlsplit(route.request.url).query)
        page = int(query['page'][0])
        size = int(query['page_size'][0])
        filtered = query.get('city', [''])[0] or query.get('delivery_only') == ['true']
        total = 3 if filtered else 75
        items = [{'id': i, 'price': i * 100, 'title': title or f'Объявление {i}',
                  'source_key': 'web:1', 'ad_url': 'https://avito.ru/ad', 'city': 'Москва'}
                 for i in range((page - 1) * size + 1, min(page * size, total) + 1)]
        reply(route, {'items': items, 'total': total, 'page': page, 'page_size': size})

    def handler(route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path
        if url.hostname != 'avito.test':
            route.abort()
        elif not path.startswith('/api/'):
            asset = (DIST / (path.lstrip('/') or 'index.html')).resolve()
            if DIST not in asset.parents or not asset.is_file():
                route.fulfill(status=404)
            else:
                route.fulfill(body=asset.read_bytes(), content_type=mimetypes.guess_type(asset)[0] or 'application/octet-stream')
        elif path == '/api/login':
            state['login'].append(route)
        elif path == '/api/me':
            reply(route, {'id': 1, 'username': 'owner', 'is_admin': False})
        elif path == '/api/logout':
            state['logout'] += 1
            reply(route, {'ok': True})
        elif path == '/api/links' and request.method == 'GET':
            reply(route, state['links'])
        elif path == '/api/links' and request.method == 'POST':
            if 'example.com' in request.post_data_json['url']:
                reply(route, {'detail': [{'loc': ['body', 'url'], 'msg': 'Value error, Укажите ссылку Avito'}]}, 422)
            else:
                state['save'].append(route)
        elif path == '/api/ads/page':
            state['queries'].append(parse_qs(url.query))
            if state['unauthorized']:
                reply(route, {'detail': 'Требуется авторизация'}, 401)
            elif state['fail_ads']:
                reply(route, {'detail': 'Временно недоступен'}, 503)
            elif state['hold_ads']:
                state['ads'].append(route)
            else:
                ads_reply(route)
        else:
            raise AssertionError(f'Unexpected request: {request.method} {path}')

    with sync_playwright() as p:
        options = {'headless': True}
        if os.environ.get('BROWSER_EXECUTABLE'):
            options['executable_path'] = os.environ['BROWSER_EXECUTABLE']
        browser = p.chromium.launch(**options)
        context = browser.new_context()
        context.route('**/*', handler)
        page = context.new_page()
        page.clock.install()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://avito.test/')
        page.get_by_label('Логин', exact=True).fill('owner')
        page.get_by_label('Пароль', exact=True).fill('password')
        page.get_by_role('button', name='Войти', exact=True).click()
        expect(page.get_by_role('button', name='Подождите…')).to_be_disabled()
        page.locator('form').evaluate("form => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))")
        assert len(state['login']) == 1
        reply(state['login'].pop(), {'token': 'browser-token', 'username': 'owner', 'is_admin': False})

        expect(page.get_by_role('heading', name='Мои ссылки для парсинга')).to_be_visible()
        page.get_by_label('Ссылка Avito', exact=True).fill('https://example.com')
        page.get_by_role('button', name='Добавить', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('Ссылка: Укажите ссылку Avito')
        expect(page.get_by_label('Ссылка Avito', exact=True)).to_be_visible()
        page.get_by_label('Ссылка Avito', exact=True).fill('https://www.avito.ru/search?q=cpu')
        page.get_by_role('button', name='Добавить', exact=True).click()
        expect(page.get_by_role('button', name='Сохраняем…')).to_be_disabled()
        page.locator('form').evaluate("form => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))")
        assert len(state['save']) == 1
        route = state['save'].pop()
        link = {**route.request.post_data_json, 'id': 1}
        state['links'] = [link]
        reply(route, link, 201)
        expect(page.get_by_role('alert')).to_have_count(0)

        state['hold_ads'] = True
        page.get_by_role('button', name='cpu', exact=True).click()
        expect(page.get_by_text('Загружаем объявления…')).to_be_visible()
        expect(page.get_by_text('Нет объявлений по заданным условиям.')).to_have_count(0)
        page.wait_for_timeout(50)
        assert len(state['ads']) == 1
        state['hold_ads'] = False
        ads_reply(state['ads'].pop())
        expect(page.locator('tbody tr')).to_have_count(50)
        state['fail_ads'] = True
        page.clock.run_for(10001)
        expect(page.get_by_role('alert')).to_contain_text('Временно недоступен')
        expect(page.locator('tbody tr')).to_have_count(50)
        state['fail_ads'] = False
        page.clock.run_for(10001)
        expect(page.get_by_role('alert')).to_have_count(0)
        page.get_by_role('button', name='Следующая').click()
        expect(page.locator('tbody tr')).to_have_count(25)
        assert state['queries'][-1]['page'] == ['2']
        page.get_by_role('button', name='Цена', exact=True).click()
        expect(page.locator('tbody tr')).to_have_count(50)
        assert state['queries'][-1]['page'] == ['1']
        assert state['queries'][-1]['sort'] == ['price']

        state['hold_ads'] = True
        page.get_by_label('Локация', exact=True).select_option('Москва')
        expect(page.get_by_text('Загружаем объявления…')).to_be_visible()
        page.wait_for_timeout(50)
        stale = state['ads'].pop()
        state['hold_ads'] = False
        page.get_by_label('Локация', exact=True).select_option('Новосибирск')
        expect(page.locator('tbody tr')).to_have_count(3)
        ads_reply(stale, title='Устаревший ответ')
        expect(page.get_by_text('Устаревший ответ')).to_have_count(0)
        assert state['queries'][-1]['city'] == ['Новосибирск']

        state['unauthorized'] = True
        page.get_by_label('Только с доставкой').check()
        expect(page.get_by_role('button', name='Войти', exact=True)).to_be_visible()
        expect(page.get_by_role('alert')).to_contain_text('Сессия завершена')
        assert page.evaluate("localStorage.getItem('token')") is None
        page.get_by_label('Логин', exact=True).fill('owner')
        page.get_by_label('Пароль', exact=True).fill('password')
        page.get_by_role('button', name='Войти', exact=True).click()
        expect(page.get_by_role('button', name='Подождите…')).to_be_disabled()
        reply(state['login'].pop(), {'token': 'new-token', 'username': 'owner', 'is_admin': False})
        expect(page.get_by_role('button', name='cpu', exact=True)).to_be_visible()
        page.get_by_role('button', name='Выйти', exact=True).click()
        expect(page.get_by_role('button', name='Войти', exact=True)).to_be_visible()
        assert state['logout'] == 1
        assert not errors, errors
        browser.close()
    print('Browser smoke passed: login, duplicate submits, validation, pagination, polling recovery, sorting, stale requests, 401, logout')


if __name__ == '__main__':
    main()
