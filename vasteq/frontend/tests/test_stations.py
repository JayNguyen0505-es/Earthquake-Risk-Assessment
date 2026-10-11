"""Station-management browser checks; API calls are intercepted."""
import json
import os
import unittest
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get('VASTEQ_FRONTEND_URL', 'http://127.0.0.1:28080').rstrip('/')
ADMIN = {'id': 1, 'displayName': 'Admin', 'email': 'admin@example.com', 'role': 'admin', 'enabled': True}
STATION = {'id': 1, 'networkCode': 'VN', 'stationCode': '4001', 'name': 'Station A', 'province': 'Sơn La',
           'city': 'City A', 'latitude': 0, 'longitude': 0, 'coordinateCrs': None, 'elevationM': 0,
           'instrumentType': 'Palert', 'instrumentSerial': '00123', 'metadataUri': 'data/station.xml', 'metadataSource': 'Spreadsheet'}


class StationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.ctx = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        self.ctx.add_init_script("if (location.pathname !== '/login.html') sessionStorage.setItem('vasteq.accessToken', 'test-token')")
        self.page = self.ctx.new_page()
        self.viewer = dict(ADMIN)
        self.records = [dict(STATION), {**STATION, 'id': 2, 'stationCode': '4002', 'name': '<img src=x onerror=alert(1)>', 'latitude': None, 'longitude': None}]
        self.calls = []
        self.errors = []
        self.fail = {}
        self.hold = False
        self.pending = []
        self.page.on('pageerror', lambda err: self.errors.append(str(err)))
        self.page.route('**/api/v1/user/me', lambda route: self.reply(route, self.viewer))
        self.page.route('**/api/v1/station**', self.api)

    def tearDown(self):
        self.ctx.close()
        self.assertEqual(self.errors, [])

    def reply(self, route, data=None, status=200):
        route.fulfill(status=status, content_type='application/json', body=json.dumps(data) if data is not None else '')

    def api(self, route):
        req = route.request
        path = urlparse(req.url).path
        method = req.method
        data = req.post_data_json if req.post_data else None
        self.calls.append((method, path, data, req.url, req.headers))
        fail = self.fail.pop(method, None)
        if fail:
            if fail == 'network':
                route.abort('failed')
            else:
                self.reply(route, fail[1], fail[0])
            return
        if method == 'GET':
            params = parse_qs(urlparse(req.url).query)
            items = self.records
            if 'search' in params:
                items = [s for s in items if params['search'][0].lower() in (s['name'] or '').lower()]
            if 'province' in params:
                items = [s for s in items if s['province'] == params['province'][0]]
            if 'hasCoordinates' in params:
                items = [s for s in items if (s['latitude'] is not None) == (params['hasCoordinates'][0] == 'true')]
            offset = int(params.get('offset', ['0'])[0])
            limit = int(params.get('limit', ['20'])[0])
            self.reply(route, {'items': items[offset:offset + limit], 'total': len(items), 'offset': offset, 'limit': limit})
        elif method == 'POST':
            if self.hold:
                self.pending.append(route)
                return
            item = {**data, 'id': max((s['id'] for s in self.records), default=0) + 1}
            self.records.append(item)
            self.reply(route, item, 201)
        elif method == 'PATCH':
            item = next(s for s in self.records if s['id'] == int(path.split('/')[-1]))
            item.update(data)
            self.reply(route, item)
        elif method == 'DELETE':
            self.records = [s for s in self.records if s['id'] != int(path.split('/')[-1])]
            self.reply(route, status=204)

    def open(self):
        self.page.goto(BASE + '/stations.html')
        expect(self.page.locator('#list-status')).to_contain_text('of')

    def add(self):
        self.page.locator('#add').click()
        expect(self.page.locator('#network')).to_be_focused()
        self.page.locator('#network').fill('VN')
        self.page.locator('#code').fill('NEW01')

    def writes(self):
        return [call for call in self.calls if call[0] != 'GET']

    def test_list_unknown_coordinates_safe_text_and_icons(self):
        self.open()
        expect(self.page.locator('thead th')).to_have_text(['ID', 'Station', 'Name', 'Province', 'Latitude', 'Longitude', 'Actions'])
        expect(self.page.locator('#rows tr').nth(0).locator('td').nth(4)).to_have_text('0')
        expect(self.page.locator('#rows tr').nth(1).locator('td').nth(4)).to_have_text('—')
        expect(self.page.locator('#rows')).to_contain_text('<img src=x onerror=alert(1)>')
        expect(self.page.locator('#rows img')).to_have_count(0)
        expect(self.page.get_by_role('button', name='Edit VN.4001')).to_have_text('')
        expect(self.page.locator('.admin-nav [aria-current]')).to_have_text('Stations')

    def test_add_preserves_serial_and_sends_unknown_as_null(self):
        self.open(); self.add()
        self.page.locator('#name').fill('New station')
        self.page.locator('#serial').fill('00007')
        self.page.locator('#save').click()
        expect(self.page.locator('#edit-box')).not_to_be_visible()
        expect(self.page.locator('#rows')).to_contain_text('VN.NEW01')
        expect(self.page.locator('#toasts')).to_contain_text('Station added successfully.')
        call = self.writes()[0]
        self.assertEqual(call[:2], ('POST', '/api/v1/station'))
        self.assertEqual(call[2]['instrumentSerial'], '00007')
        self.assertIsNone(call[2]['latitude'])
        self.assertIsNone(call[2]['longitude'])
        self.assertIsNone(call[2]['coordinateCrs'])
        self.assertEqual(len(call[2]), 13)
        self.assertEqual(call[4]['authorization'], 'Bearer test-token')

    def test_edit_prefills_metadata_and_can_clear_coordinates(self):
        self.open()
        self.page.get_by_role('button', name='Edit VN.4001').click()
        expect(self.page.locator('#serial')).to_have_value('00123')
        expect(self.page.locator('#lat')).to_have_value('0')
        expect(self.page.locator('#elevation')).to_have_value('0')
        expect(self.page.locator('#uri')).to_have_value('data/station.xml')
        self.page.locator('#lat').fill('')
        self.page.locator('#lng').fill('')
        self.page.locator('#name').fill('Updated station')
        self.page.locator('#save').click()
        expect(self.page.locator('#toasts')).to_contain_text('Station updated successfully.')
        expect(self.page.locator('#rows')).to_contain_text('Updated station')
        call = self.writes()[0]
        self.assertEqual(call[:2], ('PATCH', '/api/v1/station/1'))
        self.assertIsNone(call[2]['latitude'])
        self.assertIsNone(call[2]['longitude'])
        self.assertEqual(call[2]['instrumentSerial'], '00123')

    def test_code_range_and_coordinate_pair_validation(self):
        self.open(); self.add()
        self.page.locator('#network').fill('V ')
        self.page.locator('#save').click()
        self.assertEqual(self.writes(), [])
        self.page.locator('#network').fill('VN')
        self.page.locator('#lat').fill('91')
        self.page.locator('#save').click()
        self.assertEqual(self.writes(), [])
        self.page.locator('#lat').fill('21')
        self.page.locator('#save').click()
        expect(self.page.locator('#edit-error')).to_contain_text('both latitude and longitude')
        expect(self.page.locator('#lng')).to_be_focused()
        self.assertEqual(self.writes(), [])
        self.page.locator('#lng').fill('105')
        self.page.locator('#save').click()
        expect(self.page.locator('#edit-box')).not_to_be_visible()
        self.assertEqual(self.writes()[0][2]['latitude'], 21)
        self.assertEqual(self.writes()[0][2]['longitude'], 105)

    def test_filters_pagination_clear_and_empty_results(self):
        self.records = [{**STATION, 'id': i, 'stationCode': str(i)} for i in range(1, 24)]
        self.open()
        self.page.locator('#search').fill('Station')
        self.page.locator('#area').fill('Sơn La')
        self.page.locator('#coords').select_option('true')
        self.page.get_by_role('button', name='Apply', exact=True).click()
        expect(self.page.locator('#list-status')).to_have_text('Showing 1–20 of 23 stations')
        self.page.locator('#next').click()
        expect(self.page.locator('#list-status')).to_have_text('Showing 21–23 of 23 stations')
        params = parse_qs(urlparse(self.calls[-1][3]).query)
        self.assertEqual(params, {'search': ['Station'], 'province': ['Sơn La'], 'hasCoordinates': ['true'], 'offset': ['20'], 'limit': ['20']})
        self.page.locator('#coords').select_option('false')
        self.page.get_by_role('button', name='Apply', exact=True).click()
        expect(self.page.locator('#list-status')).to_have_text('0 stations')
        expect(self.page.locator('#rows')).to_contain_text('No stations found')
        self.page.locator('#clear').click()
        expect(self.page.locator('#list-status')).to_have_text('Showing 1–20 of 23 stations')
        self.assertNotIn('hasCoordinates', parse_qs(urlparse(self.calls[-1][3]).query))

    def test_delete_confirmation_conflict_and_last_page(self):
        self.records += [{**STATION, 'id': i, 'stationCode': str(i)} for i in range(3, 22)]
        self.open()
        self.page.get_by_role('button', name='Delete VN.4001').click()
        self.page.locator('#del-box').get_by_role('button', name='Cancel', exact=True).click()
        self.assertEqual(self.writes(), [])
        self.fail['DELETE'] = (409, {'code': 'station_in_use'})
        self.page.get_by_role('button', name='Delete VN.4001').click()
        self.page.locator('#delete').click()
        expect(self.page.locator('#del-error')).to_contain_text('linked channels')
        expect(self.page.locator('#delete')).to_be_enabled()
        self.page.keyboard.press('Escape')
        self.page.locator('#next').click()
        expect(self.page.locator('#list-status')).to_have_text('Showing 21–21 of 21 stations')
        self.page.get_by_role('button', name='Delete VN.21', exact=True).click()
        self.page.locator('#delete').click()
        expect(self.page.locator('#toasts')).to_contain_text('Station deleted successfully.')
        expect(self.page.locator('#list-status')).to_have_text('Showing 1–20 of 20 stations')

    def test_duplicate_codes_and_busy_submission(self):
        self.open(); self.add()
        self.fail['POST'] = (409, {'code': 'station_exists'})
        self.page.locator('#save').click()
        expect(self.page.locator('#edit-error')).to_contain_text('already exists')
        expect(self.page.locator('#code')).to_have_value('NEW01')
        self.hold = True
        self.page.locator('#save').click()
        expect(self.page.locator('#save')).to_be_disabled()
        self.page.evaluate("document.querySelector('#edit-form').requestSubmit()")
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#edit-box')).to_be_visible()
        self.assertEqual(len(self.pending), 1)
        self.reply(self.pending[0], {**STATION, 'id': 3}, 201)
        expect(self.page.locator('#edit-box')).not_to_be_visible()

    def test_admin_access_retry_and_expired_session(self):
        self.viewer['role'] = 'user'
        self.page.goto(BASE + '/stations.html')
        expect(self.page.locator('#access-status')).to_contain_text('Administrator access is required')
        self.assertEqual(self.calls, [])
        self.viewer['role'] = 'admin'
        self.fail['GET'] = 'network'
        self.page.reload()
        expect(self.page.locator('#retry-list')).to_be_visible()
        self.page.locator('#retry-list').click()
        expect(self.page.locator('#rows tr')).to_have_count(2)
        self.fail['GET'] = (401, None)
        self.page.locator('#clear').click()
        expect(self.page).to_have_url(BASE + '/login.html')
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"))

    def test_mobile_layout_dialog_and_navigation(self):
        self.open()
        for width in (320, 390, 768, 1280):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.page.set_viewport_size({'width': 320, 'height': 700})
        self.add()
        box = self.page.locator('#edit-box').bounding_box()
        self.assertGreaterEqual(box['x'], 0)
        self.assertLessEqual(box['x'] + box['width'], 320)
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#add')).to_be_focused()
        self.page.get_by_role('navigation', name='Administration', exact=True).get_by_role('link', name='Users', exact=True).click()
        expect(self.page).to_have_url(BASE + '/users.html')
        self.page.goto(BASE + '/index.html')
        expect(self.page.get_by_role('link', name='Manage stations')).to_be_visible()


if __name__ == '__main__':
    unittest.main()
