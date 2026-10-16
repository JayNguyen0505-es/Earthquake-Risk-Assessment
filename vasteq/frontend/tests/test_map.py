"""Station-map browser checks; APIs and external tiles are intercepted."""
import base64
import json
import os
import unittest
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get('VASTEQ_FRONTEND_URL', 'http://127.0.0.1:28080').rstrip('/')
USER = {'id': 1, 'displayName': 'Viewer', 'email': 'viewer@example.com', 'role': 'user', 'enabled': True}
STATION = {'id': 1, 'networkCode': 'VN', 'stationCode': '4001', 'name': '<img src=x onerror=alert(1)>',
           'province': 'Sơn La', 'city': 'City A', 'latitude': 0, 'longitude': 0,
           'elevationM': 0, 'coordinateCrs': None, 'instrumentType': 'Palert'}
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j8ioAAAAASUVORK5CYII=')


class MapTest(unittest.TestCase):
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
        self.page = self.ctx.new_page()
        self.viewer = dict(USER)
        self.records = [dict(STATION), {**STATION, 'id': 2, 'stationCode': '4002', 'name': 'Pending', 'latitude': None, 'longitude': None},
                        {**STATION, 'id': 3, 'stationCode': '4003', 'name': 'Station C', 'province': 'Điện Biên',
                         'latitude': 21.5, 'longitude': 103, 'coordinateCrs': 'EPSG:4326'}]
        self.calls = []
        self.requests = []
        self.errors = []
        self.fail = None
        self.fail_offset = 0
        self.me_fail = False
        self.tile_fail = False
        self.pending = []
        self.hold = False
        self.page.on('pageerror', lambda err: self.errors.append(str(err)))
        self.page.on('request', lambda req: self.requests.append(req))
        self.page.route('**/api/v1/user/me', self.me)
        self.page.route('**/api/v1/station**', self.api)
        self.page.route('https://tile.openstreetmap.org/**', self.tile)

    def tearDown(self):
        self.ctx.close()
        self.assertEqual(self.errors, [])
        allowed = {urlparse(BASE).netloc, 'tile.openstreetmap.org'}
        self.assertTrue(all(urlparse(req.url).netloc in allowed for req in self.requests))
        for req in self.requests:
            if urlparse(req.url).netloc == 'tile.openstreetmap.org':
                self.assertNotIn('authorization', req.headers)

    def reply(self, route, data, status=200):
        route.fulfill(status=status, content_type='application/json', body=json.dumps(data))

    def me(self, route):
        if self.me_fail:
            route.abort('failed')
        else:
            self.reply(route, self.viewer)

    def tile(self, route):
        if self.tile_fail:
            route.fulfill(status=503)
        else:
            route.fulfill(content_type='image/png', body=PNG)

    def api(self, route):
        req = route.request
        params = parse_qs(urlparse(req.url).query)
        self.calls.append((params, req.headers))
        offset = int(params.get('offset', ['0'])[0])
        if self.fail and offset == self.fail_offset:
            fail, self.fail = self.fail, None
            if fail == 'network':
                route.abort('failed')
            else:
                self.reply(route, {'message': 'Access unavailable'}, fail)
            return
        items = self.records
        if 'search' in params:
            items = [s for s in items if params['search'][0].lower() in (s['name'] or '').lower()]
        if 'province' in params:
            items = [s for s in items if s['province'] == params['province'][0]]
        if 'hasCoordinates' in params:
            items = [s for s in items if (s['latitude'] is not None) == (params['hasCoordinates'][0] == 'true')]
        limit = int(params.get('limit', ['20'])[0])
        data = {'items': items[offset:offset + limit], 'total': len(items), 'offset': offset, 'limit': limit}
        if self.hold:
            self.pending.append((route, data))
        else:
            self.reply(route, data)

    def token(self):
        self.ctx.add_init_script("if (location.pathname !== '/login.html') sessionStorage.setItem('vasteq.accessToken', 'test-token')")

    def open(self):
        self.token()
        self.page.goto(BASE + '/map.html')
        expect(self.page.locator('#map-status')).to_contain_text('stations mapped')

    def test_popup_missing_zero_coordinates_and_safe_text(self):
        self.open()
        expect(self.page.locator('.leaflet-marker-icon')).to_have_count(2)
        expect(self.page.locator('#map-status')).to_have_text('2 of 3 stations mapped · 1 missing coordinates')
        expect(self.page.locator('#crs-note')).to_contain_text('1 mapped station has no specified coordinate system')
        self.page.locator('#focus').select_option('1')
        popup = self.page.locator('.station-popup')
        expect(popup).to_contain_text(STATION['name'])
        expect(popup.locator('img')).to_have_count(0)
        expect(popup.locator('dd')).to_have_text(['Sơn La', 'City A', '0', '0', '0', 'Not specified', 'Palert'])
        self.page.locator('#focus').select_option('3')
        expect(popup).to_have_count(1)
        expect(popup).to_contain_text('EPSG:4326')
        expect(self.page.locator('.leaflet-control-attribution')).to_contain_text('OpenStreetMap')

    def test_every_api_page_is_mapped_and_authenticated(self):
        self.records = [{**STATION, 'id': i, 'stationCode': str(i), 'name': 'Station',
                         'latitude': 21 + i / 1000, 'longitude': 103 + i / 1000} for i in range(1, 202)]
        self.open()
        expect(self.page.locator('.leaflet-marker-icon')).to_have_count(201)
        self.assertEqual([p['offset'] for p, _ in self.calls], [['0'], ['100'], ['200']])
        for params, headers in self.calls:
            self.assertEqual(params['limit'], ['100'])
            self.assertEqual(headers['authorization'], 'Bearer test-token')
        self.page.locator('#focus').select_option('201')
        expect(self.page.locator('.station-popup')).to_contain_text('VN.201')

    def test_filters_refresh_clear_and_empty_results(self):
        self.open()
        self.page.locator('#search').fill('  Station  ')
        self.page.locator('#area').fill('Điện Biên')
        self.page.locator('#coords').select_option('true')
        self.page.get_by_role('button', name='Apply', exact=True).click()
        expect(self.page.locator('#map-status')).to_have_text('1 of 1 stations mapped · 0 missing coordinates')
        params = {'search': ['Station'], 'province': ['Điện Biên'], 'hasCoordinates': ['true'], 'offset': ['0'], 'limit': ['100']}
        self.assertEqual(self.calls[-1][0], params)
        self.records.append({**self.records[2], 'id': 4, 'stationCode': '4004'})
        self.page.locator('#refresh').click()
        expect(self.page.locator('.leaflet-marker-icon')).to_have_count(2)
        self.assertEqual(self.calls[-1][0], params)
        self.page.locator('#coords').select_option('false')
        self.page.get_by_role('button', name='Apply', exact=True).click()
        expect(self.page.locator('#empty')).to_contain_text('No stations found')
        expect(self.page.locator('.leaflet-marker-icon')).to_have_count(0)
        self.page.locator('#clear').click()
        expect(self.page.locator('.leaflet-marker-icon')).to_have_count(3)
        self.page.locator('#coords').select_option('false')
        self.page.get_by_role('button', name='Apply', exact=True).click()
        expect(self.page.locator('#empty')).to_contain_text('no coordinates to plot')
        expect(self.page.locator('#map-status')).to_have_text('0 of 1 stations mapped · 1 missing coordinates')
        expect(self.page.locator('#fit')).to_be_disabled()
        expect(self.page.locator('#focus')).to_be_disabled()

    def test_partial_page_failure_retry_and_busy_controls(self):
        self.records = [{**STATION, 'id': i, 'stationCode': str(i)} for i in range(1, 102)]
        self.fail = 'network'
        self.fail_offset = 100
        self.token()
        self.page.goto(BASE + '/map.html')
        expect(self.page.locator('#page-error')).to_contain_text('Unable to reach the server')
        expect(self.page.locator('.leaflet-marker-icon')).to_have_count(0)
        self.hold = True
        self.page.locator('#refresh').click()
        expect(self.page.locator('#refresh')).to_be_disabled()
        expect(self.page.locator('#search')).to_be_disabled()
        self.page.evaluate("document.querySelector('#refresh').click()")
        self.assertEqual(len(self.pending), 1)
        self.hold = False
        self.reply(*self.pending[0])
        expect(self.page.locator('.leaflet-marker-icon')).to_have_count(101)
        expect(self.page.locator('#page-error')).to_be_hidden()
        expect(self.page.locator('#refresh')).to_be_enabled()

    def test_session_retry_guest_admin_navigation_and_sign_out(self):
        self.me_fail = True
        self.token()
        self.page.goto(BASE + '/map.html')
        expect(self.page.locator('#retry-access')).to_be_visible()
        self.assertEqual(self.calls, [])
        self.me_fail = False
        self.viewer['role'] = 'guest'
        self.page.locator('#retry-access').click()
        expect(self.page.locator('.leaflet-marker-icon')).to_have_count(2)
        expect(self.page.locator('#admin-nav')).to_be_hidden()
        self.viewer['role'] = 'admin'
        self.page.reload()
        expect(self.page.locator('#admin-nav [aria-current]')).to_have_text('Map')
        self.page.goto(BASE + '/stations.html')
        self.page.get_by_role('navigation', name='Administration', exact=True).get_by_role('link', name='Map', exact=True).click()
        expect(self.page).to_have_url(BASE + '/map.html')
        self.page.goto(BASE + '/index.html')
        self.page.get_by_role('link', name='Station map', exact=True).click()
        expect(self.page).to_have_url(BASE + '/map.html')
        self.page.locator('#sign-out').click()
        expect(self.page).to_have_url(BASE + '/login.html')
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"))

    def test_no_session_expired_session_and_forbidden_access(self):
        self.page.goto(BASE + '/map.html')
        expect(self.page).to_have_url(BASE + '/login.html')
        self.assertEqual(self.calls, [])
        self.assertFalse(any('tile.openstreetmap.org' in req.url for req in self.requests))
        self.token()
        self.fail = 403
        self.page.goto(BASE + '/map.html')
        expect(self.page.locator('#access-status')).to_contain_text('Station access is unavailable')
        expect(self.page.locator('#stations')).to_be_hidden()
        self.records = [{**STATION, 'id': i} for i in range(1, 102)]
        self.fail = 401
        self.fail_offset = 100
        self.page.reload()
        expect(self.page).to_have_url(BASE + '/login.html')
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"))

    def test_tile_failure_retry_keyboard_markers_fit_and_mobile_layout(self):
        self.records = [{**STATION, 'latitude': 21.8, 'longitude': 103.3}]
        self.tile_fail = True
        self.open()
        expect(self.page.locator('#tile-note')).to_be_visible()
        marker = self.page.get_by_role('button', name='VN.4001', exact=True)
        marker.focus()
        self.page.keyboard.press('Enter')
        expect(self.page.locator('.station-popup')).to_be_visible()
        self.tile_fail = False
        self.page.locator('#retry-tiles').click()
        expect(self.page.locator('#tile-note')).to_be_hidden()
        self.page.locator('#focus').select_option('1')
        self.page.locator('#fit').click()
        expect(self.page.locator('.station-popup')).not_to_be_visible()
        expect(self.page.locator('#focus')).to_have_value('')
        self.page.locator('#focus').select_option('1')
        for width in (320, 390, 768, 1280):
            self.page.set_viewport_size({'width': width, 'height': 900})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            self.page.wait_for_function("""() => {
                const map = document.querySelector('#map').getBoundingClientRect();
                const box = document.querySelector('.leaflet-popup').getBoundingClientRect();
                return box.left >= map.left && box.right <= map.right;
            }""")
        self.page.set_viewport_size({'width': 320, 'height': 700})
        self.page.locator('#focus').select_option('1')
        expect(self.page.locator('.station-popup')).to_be_visible()
        box = self.page.locator('#map').bounding_box()
        self.assertGreaterEqual(box['x'], 0)
        self.assertLessEqual(box['x'] + box['width'], 320)


if __name__ == '__main__':
    unittest.main()
