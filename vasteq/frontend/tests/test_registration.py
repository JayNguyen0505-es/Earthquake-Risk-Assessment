"""Browser checks against a running backend; API responses are intercepted.

Run with Python's unittest and the optional Playwright testing dependency.
These tests never create database accounts.
"""
import json
import os
import unittest
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("VASTEQ_FRONTEND_URL", "http://127.0.0.1:8080").rstrip("/")
API = "**/api/v1/user/register"
PASSWORD = "browser-test-password"


class RegistrationTest(unittest.TestCase):
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
        self.page.goto(BASE + "/register.html")
        expect(self.page.locator("#submit-button")).to_be_enabled()

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])
        self.assertTrue(all(urlparse(url).netloc == urlparse(BASE).netloc for url in self.requests),
                        "Page made an external request")

    def fill(self):
        self.page.get_by_label("Display name", exact=True).fill("Test User")
        self.page.get_by_label("Email", exact=True).fill("browser@example.com")
        self.page.get_by_label("Password", exact=True).fill(PASSWORD)
        self.page.get_by_label("Confirm password", exact=True).fill(PASSWORD)

    def test_inline_validation_blocks_invalid_requests(self):
        requests = []
        self.page.route(API, lambda route: (requests.append(route.request), route.abort()))
        self.page.get_by_role("button", name="Create account", exact=True).click()
        expect(self.page.locator("#display-name-error")).to_have_text("Enter your display name.")
        expect(self.page.locator("#display-name")).to_be_focused()
        self.page.locator("#display-name").fill("   ")
        self.page.locator("#email").fill("invalid-email")
        self.page.locator("#password").fill("short")
        self.page.locator("#confirm-password").fill("different")
        self.page.get_by_role("button", name="Create account", exact=True).click()
        expect(self.page.locator("#email-error")).to_have_text("Enter a valid email address.")
        expect(self.page.locator("#password-error")).to_have_text("Use 12–128 characters.")
        expect(self.page.locator("#confirm-password-error")).to_have_text("Passwords do not match.")
        self.assertEqual(requests, [])

    def test_success_payload_loading_and_duplicate_submission(self):
        pending = []
        self.page.evaluate("sessionStorage.setItem('vasteq.accessToken', 'stale-token')")
        self.page.route(API, lambda route: pending.append(route))
        self.fill()
        self.page.locator("#display-name").fill(" Test User ")
        self.page.get_by_role("button", name="Create account", exact=True).click()
        expect(self.page.locator("#submit-button")).to_be_disabled()
        expect(self.page.locator("#submit-label")).to_have_text("Creating account…")
        self.page.evaluate("document.querySelector('#register-form').requestSubmit()")
        self.assertEqual(len(pending), 1)
        request = pending[0].request
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.post_data_json, {"displayName": "Test User", "email": "browser@example.com", "password": PASSWORD})
        self.assertNotIn("authorization", request.headers)
        pending[0].fulfill(status=201, content_type="application/json", body=json.dumps({"id": 1, "email": "browser@example.com"}))
        expect(self.page.get_by_role("heading", name="Account created successfully")).to_be_visible()
        expect(self.page.locator("#page-title")).to_be_focused()
        expect(self.page.locator("#register-form")).to_be_hidden()
        expect(self.page.locator("#registration-success a")).to_have_attribute("href", "login.html")
        self.assertEqual(self.page.locator("#password").input_value(), "")
        self.assertEqual(self.page.locator("#confirm-password").input_value(), "")

    def test_duplicate_email_can_be_corrected_and_retried(self):
        calls = []
        def respond(route):
            calls.append(route.request)
            status = 409 if len(calls) == 1 else 201
            body = {"code": "email_exists", "message": "Duplicate"} if status == 409 else {"id": 1}
            route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
        self.page.route(API, respond)
        self.fill()
        self.page.locator("#submit-button").click()
        expect(self.page.locator("#email-error")).to_contain_text("already exists")
        expect(self.page.locator("#email")).to_be_focused()
        self.assertEqual(self.page.locator("#password").input_value(), PASSWORD)
        self.page.locator("#email").fill("another@example.com")
        expect(self.page.locator("#email-error")).to_have_text("")
        self.page.locator("#submit-button").click()
        expect(self.page.locator("#registration-success")).to_be_visible()
        self.assertEqual(len(calls), 2)

    def test_network_failure_preserves_form_for_retry(self):
        self.page.route(API, lambda route: route.abort("failed"))
        self.fill()
        self.page.locator("#submit-button").click()
        expect(self.page.get_by_role("alert")).to_have_text("Unable to reach the server. Please try again.")
        expect(self.page.locator("#submit-button")).to_be_enabled()
        self.assertEqual(self.page.locator("#display-name").input_value(), "Test User")
        self.assertEqual(self.page.locator("#password").input_value(), PASSWORD)

    def test_server_error_does_not_display_internal_html(self):
        self.page.route(API, lambda route: route.fulfill(status=500, content_type="text/html", body="<h1>Internal database details</h1>"))
        self.fill()
        self.page.locator("#submit-button").click()
        expect(self.page.get_by_role("alert")).to_have_text("We couldn't create your account. Please try again.")
        expect(self.page.locator("#submit-button")).to_be_enabled()

    def test_password_toggles_and_keyboard_navigation(self):
        self.page.keyboard.press("Tab")
        expect(self.page.get_by_role("link", name="VAST-Earthquake home", exact=True)).to_be_focused()
        self.page.keyboard.press("Tab")
        expect(self.page.locator("#display-name")).to_be_focused()
        self.page.get_by_role("button", name="Show password", exact=True).click()
        expect(self.page.locator("#password")).to_have_attribute("type", "text")
        expect(self.page.get_by_role("button", name="Hide password", exact=True)).to_have_attribute("aria-pressed", "true")
        self.page.get_by_role("button", name="Hide password", exact=True).click()
        expect(self.page.locator("#password")).to_have_attribute("type", "password")
        self.page.get_by_role("button", name="Show confirmation password", exact=True).click()
        expect(self.page.locator("#confirm-password")).to_have_attribute("type", "text")

    def test_mobile_layout_and_reduced_motion(self):
        for width in (320, 390, 768, 1280):
            self.page.set_viewport_size({"width": width, "height": 900})
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
            box = self.page.locator(".auth-card").bounding_box()
            self.assertGreaterEqual(box["x"], 0)
            self.assertLessEqual(box["x"] + box["width"], width)
        self.page.emulate_media(reduced_motion="reduce")
        self.assertEqual(self.page.locator(".button-spinner").evaluate("e => getComputedStyle(e).animationName"), "none")


if __name__ == "__main__":
    unittest.main()
