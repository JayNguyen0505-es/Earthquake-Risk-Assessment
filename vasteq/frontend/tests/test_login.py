"""Login/session browser checks against a running backend, with intercepted APIs."""
import json
import os
import unittest
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("VASTEQ_FRONTEND_URL", "http://127.0.0.1:8080").rstrip("/")
LOGIN_API = "**/api/v1/user/login"
ME_API = "**/api/v1/user/me"
PASSWORD = " login-test-password "
TOKEN = "test-session-token"
USER = {"id": 1, "displayName": "Test User", "email": "login@example.com", "role": "user", "enabled": True}


class LoginTest(unittest.TestCase):
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
        self.page.route("**/api/v1/station*", lambda route: route.fulfill(status=200, content_type="application/json", body='{"items":[],"total":0,"offset":0,"limit":3}'))
        self.page.goto(BASE + "/login.html")

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])
        self.assertTrue(all(urlparse(url).netloc == urlparse(BASE).netloc for url in self.requests))

    def fill(self):
        self.page.get_by_label("Email", exact=True).fill("login@example.com")
        self.page.get_by_label("Password", exact=True).fill(PASSWORD)

    def success(self, route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"accessToken": TOKEN, "tokenType": "Bearer", "expiresIn": 900, "user": USER}))

    def mock_me(self):
        self.page.route(ME_API, lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(USER)))

    def test_validation_blocks_invalid_requests(self):
        requests = []
        self.page.route(LOGIN_API, lambda route: (requests.append(route.request), route.abort()))
        self.page.locator("#submit-button").click()
        expect(self.page.locator("#email-error")).to_have_text("Enter your email address.")
        expect(self.page.locator("#password-error")).to_have_text("Enter your password.")
        expect(self.page.locator("#email")).to_be_focused()
        self.page.locator("#email").fill("invalid")
        self.page.locator("#password").fill("some-password")
        self.page.locator("#submit-button").click()
        expect(self.page.locator("#email-error")).to_have_text("Enter a valid email address.")
        self.assertEqual(requests, [])

    def test_login_stores_token_and_opens_verified_home(self):
        pending = []
        me_requests = []
        self.page.evaluate("sessionStorage.setItem('vasteq.accessToken', 'stale-token')")
        self.page.route(LOGIN_API, lambda route: pending.append(route))
        def me(route):
            me_requests.append(route.request)
            route.fulfill(status=200, content_type="application/json", body=json.dumps(USER))
        self.page.route(ME_API, me)
        self.fill()
        self.page.locator("#email").fill(" login@example.com ")
        self.page.locator("#submit-button").click()
        expect(self.page.locator("#submit-button")).to_be_disabled()
        expect(self.page.locator("#submit-label")).to_have_text("Signing in…")
        self.page.evaluate("document.querySelector('#login-form').requestSubmit()")
        self.assertEqual(len(pending), 1)
        request = pending[0].request
        self.assertEqual(request.post_data_json, {"email": "login@example.com", "password": PASSWORD})
        self.assertNotIn("authorization", request.headers)
        self.success(pending[0])
        expect(self.page).to_have_url(BASE + "/index.html")
        expect(self.page.locator("#header-account")).to_be_visible()
        self.assertEqual(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"), TOKEN)
        self.assertEqual(me_requests[0].headers["authorization"], "Bearer " + TOKEN)
        self.assertEqual(self.page.evaluate("localStorage.length"), 0)
        self.assertEqual(self.page.evaluate("Object.keys(sessionStorage)"), ["vasteq.accessToken"])
        self.page.locator("#header-account").click()
        expect(self.page).to_have_url(BASE + "/account.html")
        expect(self.page.locator("#account-name")).to_have_text("Test User")

    def test_bad_credentials_preserve_inputs_and_allow_retry(self):
        calls = []
        def respond(route):
            calls.append(route.request)
            if len(calls) == 1:
                route.fulfill(status=401, content_type="application/json", body=json.dumps({"code": "unauthorized"}))
            else:
                self.success(route)
        self.page.route(LOGIN_API, respond)
        self.mock_me()
        self.fill()
        self.page.locator("#submit-button").click()
        expect(self.page.get_by_role("alert")).to_have_text("Email or password is incorrect, or your account is disabled.")
        expect(self.page.locator("#submit-button")).to_be_enabled()
        self.assertEqual(self.page.locator("#password").input_value(), PASSWORD)
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"))
        self.page.locator("#password").fill("corrected-password")
        expect(self.page.locator("#form-error")).to_be_hidden()
        self.page.locator("#submit-button").click()
        expect(self.page).to_have_url(BASE + "/index.html")

    def test_network_and_server_errors_preserve_inputs(self):
        self.page.route(LOGIN_API, lambda route: route.abort("failed"))
        self.fill()
        self.page.locator("#submit-button").click()
        expect(self.page.get_by_role("alert")).to_have_text("Unable to reach the server. Please try again.")
        expect(self.page.locator("#submit-button")).to_be_enabled()
        self.assertEqual(self.page.locator("#password").input_value(), PASSWORD)
        self.page.unroute(LOGIN_API)
        self.page.route(LOGIN_API, lambda route: route.fulfill(status=500, content_type="text/html", body="<h1>Internal server details</h1>"))
        self.page.locator("#submit-button").click()
        expect(self.page.get_by_role("alert")).to_have_text("We couldn't sign you in. Please try again.")
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"))

    def test_invalid_response_does_not_save_session(self):
        self.page.route(LOGIN_API, lambda route: route.fulfill(status=200, content_type="application/json", body='{"accessToken":"","tokenType":"Bearer"}'))
        self.fill()
        self.page.locator("#submit-button").click()
        expect(self.page.get_by_role("alert")).to_have_text("The server returned an invalid response.")
        expect(self.page).to_have_url(BASE + "/login.html")
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"))

    def test_storage_failure_keeps_login_page_and_reports_error(self):
        self.page.evaluate("() => { Storage.prototype.setItem = function() { throw new DOMException('Unavailable', 'SecurityError'); }; }")
        self.page.route(LOGIN_API, self.success)
        self.fill()
        self.page.locator("#submit-button").click()
        expect(self.page.get_by_role("alert")).to_have_text("Your browser couldn't save this session. Allow site storage and try again.")
        expect(self.page).to_have_url(BASE + "/login.html")
        expect(self.page.locator("#submit-button")).to_be_enabled()

    def test_missing_or_expired_session_returns_to_login(self):
        self.page.goto(BASE + "/account.html")
        expect(self.page).to_have_url(BASE + "/login.html")
        self.page.evaluate("sessionStorage.setItem('vasteq.accessToken', 'expired-token')")
        self.page.route(ME_API, lambda route: route.fulfill(status=401))
        self.page.goto(BASE + "/account.html")
        expect(self.page).to_have_url(BASE + "/login.html")
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"))

    def test_home_network_failure_retry_and_sign_out(self):
        self.page.evaluate("sessionStorage.setItem('vasteq.accessToken', 'test-session-token')")
        self.page.route(ME_API, lambda route: route.abort("failed"))
        self.page.goto(BASE + "/account.html")
        expect(self.page.locator("#home-error")).to_have_text("Unable to reach the server. Please try again.")
        self.assertEqual(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"), TOKEN)
        self.page.unroute(ME_API)
        self.mock_me()
        self.page.get_by_role("button", name="Try again", exact=True).click()
        expect(self.page.locator("#account-name")).to_have_text("Test User")
        self.page.get_by_role("button", name="Sign out", exact=True).click()
        expect(self.page).to_have_url(BASE + "/login.html")
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"))

    def test_password_toggle_navigation_and_mobile_layout(self):
        self.page.keyboard.press("Tab")
        expect(self.page.get_by_role("link", name="VAST-Earthquake home", exact=True)).to_be_focused()
        self.page.keyboard.press("Tab")
        expect(self.page.locator("#email")).to_be_focused()
        self.page.get_by_role("button", name="Show password", exact=True).click()
        expect(self.page.locator("#password")).to_have_attribute("type", "text")
        self.page.get_by_role("button", name="Hide password", exact=True).click()
        expect(self.page.locator("#password")).to_have_attribute("type", "password")
        for width in (320, 390, 768, 1280):
            self.page.set_viewport_size({"width": width, "height": 900})
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        self.page.get_by_role("link", name="Create an account", exact=True).click()
        expect(self.page).to_have_url(BASE + "/register.html")
        self.page.get_by_role("link", name="Sign in", exact=True).click()
        expect(self.page).to_have_url(BASE + "/login.html")


if __name__ == "__main__":
    unittest.main()
