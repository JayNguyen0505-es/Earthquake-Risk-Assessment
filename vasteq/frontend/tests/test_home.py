"""Public landing page and authenticated station-cards browser checks."""
import json
import os
import unittest
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("VASTEQ_FRONTEND_URL", "http://127.0.0.1:28080").rstrip("/")
ME = "**/api/v1/user/me"
STATIONS = "**/api/v1/station*"
USER = {"id": 1, "displayName": "Test User", "email": "test@example.com", "role": "user", "enabled": True}
RECORDS = [
    {"networkCode": "VN", "stationCode": "4001", "name": "Test station", "province": "Sơn La", "instrumentType": "Palert", "latitude": None, "longitude": None},
    {"networkCode": "VN", "stationCode": "4002", "province": "Điện Biên", "latitude": 21, "longitude": 103},
    {"networkCode": "VN", "stationCode": "4003", "name": "<img src=x onerror=alert(1)>", "latitude": None, "longitude": None},
]


class HomeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 900})
        self.page = self.context.new_page()
        self.errors = []
        self.requests = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda request: self.requests.append(request.url))

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])
        self.assertTrue(all(urlparse(url).netloc == urlparse(BASE).netloc for url in self.requests))

    def token(self):
        self.context.add_init_script("sessionStorage.setItem('vasteq.accessToken', 'test-token')")

    def me(self):
        self.page.route(ME, lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(USER)))

    def stations(self, records=RECORDS, total=20):
        self.page.route(STATIONS, lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"items": records, "total": total, "offset": 0, "limit": 3})))

    def test_public_home_at_root_and_index_requires_no_api(self):
        for path in ("/", "/index.html"):
            response = self.page.goto(BASE + path)
            self.assertEqual(response.status, 200)
            expect(self.page).to_have_url(BASE + path)
            expect(self.page.get_by_role("heading", name="Earthquake research and assessment for Northwest Vietnam")).to_be_visible()
            expect(self.page.locator("#sign-in")).to_be_visible()
            expect(self.page.locator("#my-account")).to_be_hidden()
            expect(self.page.locator("#station-login")).to_be_visible()
            self.assertEqual(self.page.locator(".tag", has_text="In development").count(), 2)
        self.assertFalse(any("/api/" in url for url in self.requests))

    def test_authenticated_preview_uses_real_fields_and_safe_text(self):
        self.token(); self.me(); self.stations()
        self.page.goto(BASE + "/index.html")
        expect(self.page.locator("#my-account")).to_be_visible()
        expect(self.page.locator("#sign-in")).to_be_hidden()
        expect(self.page.locator("#station-status")).to_have_text("Showing 3 of 20 station records.")
        cards = self.page.locator(".station-card")
        expect(cards).to_have_count(3)
        expect(cards.nth(0)).to_contain_text("VN.4001")
        expect(cards.nth(0)).to_contain_text("Coordinates pending")
        expect(cards.nth(1)).to_contain_text("Coordinates available")
        expect(cards.nth(2)).to_contain_text("<img src=x onerror=alert(1)>")
        self.assertEqual(self.page.locator("#station-cards img").count(), 0)
        self.page.locator("#my-account").click()
        expect(self.page).to_have_url(BASE + "/account.html")
        expect(self.page.locator("#name")).to_have_text("Test User")

    def test_expired_session_keeps_landing_public(self):
        self.token()
        self.page.route(ME, lambda route: route.fulfill(status=401))
        self.page.goto(BASE + "/index.html")
        self.page.wait_for_function("sessionStorage.getItem('vasteq.accessToken') === null")
        expect(self.page).to_have_url(BASE + "/index.html")
        expect(self.page.locator("#sign-in")).to_be_visible()
        expect(self.page.locator("#station-login")).to_be_visible()
        self.assertFalse(any("/api/v1/station" in url for url in self.requests))

    def test_session_network_failure_allows_retry(self):
        self.token()
        self.page.route(ME, lambda route: route.abort("failed"))
        self.page.goto(BASE + "/index.html")
        expect(self.page.locator("#session-note")).to_be_visible()
        self.assertEqual(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"), "test-token")
        self.page.unroute(ME)
        self.me(); self.stations()
        self.page.locator("#session-retry").click()
        expect(self.page.locator("#my-account")).to_be_visible()
        expect(self.page.locator("#session-note")).to_be_hidden()

    def test_station_failure_allows_retry_and_empty_inventory(self):
        self.token(); self.me()
        self.page.route(STATIONS, lambda route: route.abort("failed"))
        self.page.goto(BASE + "/index.html")
        expect(self.page.locator("#station-error")).to_be_visible()
        expect(self.page.locator("#my-account")).to_be_visible()
        self.page.unroute(STATIONS)
        self.stations([], 0)
        self.page.locator("#station-retry").click()
        expect(self.page.locator("#station-status")).to_have_text("No station records are available yet.")
        expect(self.page.locator("#station-error")).to_be_hidden()
        expect(self.page.locator(".station-card")).to_have_count(0)

    def test_expired_token_during_station_load_restores_public_view(self):
        self.token(); self.me()
        self.page.route(STATIONS, lambda route: route.fulfill(status=401))
        self.page.goto(BASE + "/index.html")
        self.page.wait_for_function("sessionStorage.getItem('vasteq.accessToken') === null")
        expect(self.page.locator("#station-list")).to_be_hidden()
        expect(self.page.locator("#sign-in")).to_be_visible()

    def test_sign_out_ignores_late_station_response(self):
        pending = []
        self.token(); self.me()
        self.page.route(STATIONS, lambda route: pending.append(route))
        self.page.goto(BASE + "/index.html")
        expect(self.page.locator("#station-status")).to_have_text("Loading station records…")
        self.page.locator("#sign-out").click()
        self.assertEqual(len(pending), 1)
        with self.page.expect_response(lambda response: "/api/v1/station" in response.url):
            pending[0].fulfill(status=200, content_type="application/json", body=json.dumps({"items": RECORDS, "total": 20}))
        self.page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        expect(self.page.locator("#station-cards")).to_be_empty()
        expect(self.page.locator("#sign-in")).to_be_visible()
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"))
        expect(self.page).to_have_url(BASE + "/index.html")

    def test_mobile_layout_and_navigation_targets(self):
        self.page.goto(BASE + "/index.html")
        for width in (320, 390, 768, 1280):
            self.page.set_viewport_size({"width": width, "height": 900})
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        self.assertTrue(self.page.evaluate("Array.from(document.querySelectorAll('a[href^=\"#\"]')).every(a => document.getElementById(a.getAttribute('href').slice(1)))"))
        self.page.get_by_role("navigation", name="Main navigation").get_by_role("link", name="Stations", exact=True).click()
        expect(self.page).to_have_url(BASE + "/index.html#stations")
        self.page.get_by_role("link", name="Sign in to explore", exact=True).click()
        expect(self.page).to_have_url(BASE + "/login.html")


if __name__ == "__main__":
    unittest.main()
