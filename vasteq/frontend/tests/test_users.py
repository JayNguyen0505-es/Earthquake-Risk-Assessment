"""User-management browser checks with intercepted API calls; no database writes."""
import json
import os
import unittest
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("VASTEQ_FRONTEND_URL", "http://127.0.0.1:28080").rstrip("/")
ADMIN = {"id": 1, "displayName": "Admin", "email": "admin@example.com", "role": "admin", "enabled": True}
MEMBER = {"id": 2, "displayName": "Member", "email": "member@example.com", "role": "user", "enabled": True}


class UsersTest(unittest.TestCase):
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
        self.context.add_init_script("if (location.pathname !== '/login.html') sessionStorage.setItem('vasteq.accessToken', 'test-admin-token')")
        self.page = self.context.new_page()
        self.viewer = dict(ADMIN)
        self.records = [dict(ADMIN), dict(MEMBER)]
        self.calls = []
        self.errors = []
        self.requests = []
        self.failures = {}
        self.pending = []
        self.hold_create = False
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda request: self.requests.append(request.url))
        self.page.route("**/api/v1/user**", self.api)

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])
        self.assertTrue(all(urlparse(url).netloc == urlparse(BASE).netloc for url in self.requests))

    def reply(self, route, body=None, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body) if body is not None else "")

    def api(self, route):
        request = route.request
        path = urlparse(request.url).path
        method = request.method
        self.calls.append((method, path, request.post_data_json if request.post_data else None, request.headers))
        failure = self.failures.pop((method, path), None)
        if failure:
            status, body = failure
            if status == 0:
                route.abort("failed")
            else:
                self.reply(route, body, status)
            return
        if path.endswith("/me"):
            self.reply(route, self.viewer)
        elif method == "GET" and path == "/api/v1/user":
            query = parse_qs(urlparse(request.url).query)
            offset = int(query.get("offset", [0])[0])
            limit = int(query.get("limit", [20])[0])
            self.reply(route, {"items": self.records[offset:offset + limit], "total": len(self.records), "offset": offset, "limit": limit})
        elif method == "POST":
            if self.hold_create:
                self.pending.append(route)
                return
            account = dict(request.post_data_json)
            account.pop("password")
            account.update(id=max(record["id"] for record in self.records) + 1, enabled=True)
            self.records.append(account)
            self.reply(route, account, 201)
        elif method == "PATCH":
            account = next(record for record in self.records if record["id"] == int(path.split("/")[-1]))
            account.update(request.post_data_json)
            self.reply(route, account)
        elif method == "DELETE":
            account = next(record for record in self.records if record["id"] == int(path.split("/")[-1]))
            account["enabled"] = False
            self.reply(route, status=204)
        else:
            self.reply(route, {"message": "Unexpected request"}, 404)

    def open(self):
        self.page.goto(BASE + "/users.html")
        expect(self.page.locator("#list-status")).to_contain_text("of")

    def fill_new_user(self):
        self.page.locator("#add-user").click()
        expect(self.page.locator("#name")).to_be_focused()
        self.page.locator("#name").fill(" New User ")
        self.page.locator("#email").fill("new@example.com")
        self.page.locator("#pass").fill("test-password-123")

    def writes(self):
        return [call for call in self.calls if call[0] in ("POST", "PATCH", "DELETE")]

    def test_add_refreshes_table_and_shows_toast(self):
        self.open()
        expect(self.page.locator("#rows tr")).to_have_count(2)
        self.fill_new_user()
        self.page.locator("#save-user").click()
        expect(self.page.locator("#edit-box")).not_to_be_visible()
        expect(self.page.locator("#rows tr")).to_have_count(3)
        expect(self.page.locator("#toasts")).to_contain_text("User added successfully.")
        method, path, payload, headers = self.writes()[0]
        self.assertEqual((method, path), ("POST", "/api/v1/user"))
        self.assertEqual(payload, {"displayName": "New User", "email": "new@example.com", "password": "test-password-123", "role": "user"})
        self.assertEqual(headers["authorization"], "Bearer test-admin-token")
        self.assertEqual(self.page.locator("#pass").input_value(), "")
        toast = self.page.locator(".toast-item").bounding_box()
        self.assertLess(toast["y"], 50)
        self.assertGreater(toast["x"], 800)
        self.page.get_by_role("button", name="Dismiss notification").click()
        expect(self.page.locator(".toast-item")).to_have_count(0)

    def test_edit_prefills_and_does_not_send_password(self):
        self.open()
        self.page.get_by_role("button", name="Edit Member", exact=True).click()
        expect(self.page.locator("#name")).to_have_value("Member")
        expect(self.page.locator("#pass-group")).to_be_hidden()
        self.page.locator("#name").fill("Updated Member")
        self.page.locator("#email").fill("updated@example.com")
        self.page.locator("#role").select_option("guest")
        self.page.locator("#save-user").click()
        expect(self.page.locator("#rows")).to_contain_text("Updated Member")
        expect(self.page.locator("#toasts")).to_contain_text("User updated successfully.")
        method, path, payload, _ = self.writes()[0]
        self.assertEqual((method, path), ("PATCH", "/api/v1/user/2"))
        self.assertEqual(payload, {"displayName": "Updated Member", "email": "updated@example.com", "role": "guest", "enabled": True})

    def test_delete_requires_confirmation_and_marks_disabled(self):
        self.open()
        self.page.get_by_role("button", name="Delete Member", exact=True).click()
        expect(self.page.locator("#del-text")).to_contain_text("record is retained")
        expect(self.page.locator("#del-box").get_by_role("button", name="Cancel", exact=True)).to_be_focused()
        self.page.locator("#del-box").get_by_role("button", name="Cancel", exact=True).click()
        self.assertEqual(self.writes(), [])
        self.page.get_by_role("button", name="Delete Member", exact=True).click()
        self.page.locator("#del-user").click()
        expect(self.page.locator("#del-box")).not_to_be_visible()
        expect(self.page.locator("#rows")).to_contain_text("Disabled")
        expect(self.page.get_by_role("button", name="Delete Member", exact=True)).to_be_disabled()
        expect(self.page.locator("#toasts")).to_contain_text("User deleted successfully")
        self.assertEqual(self.writes()[0][:2], ("DELETE", "/api/v1/user/2"))

    def test_validation_duplicate_email_and_retry(self):
        self.open()
        self.fill_new_user()
        self.page.locator("#pass").fill("short")
        self.page.locator("#save-user").click()
        self.assertEqual(self.writes(), [])
        self.page.locator("#pass").fill("test-password-123")
        self.failures[("POST", "/api/v1/user")] = (409, {"code": "email_exists"})
        self.page.locator("#save-user").click()
        expect(self.page.locator("#edit-error")).to_contain_text("already exists")
        expect(self.page.locator("#save-user")).to_be_enabled()
        expect(self.page.locator("#name")).to_have_value(" New User ")
        self.page.locator("#email").fill("other@example.com")
        self.page.locator("#save-user").click()
        expect(self.page.locator("#edit-box")).not_to_be_visible()
        expect(self.page.locator("#rows")).to_contain_text("other@example.com")

    def test_last_admin_delete_is_reported_without_closing_dialog(self):
        self.open()
        self.failures[("DELETE", "/api/v1/user/1")] = (409, {"code": "last_admin"})
        self.page.get_by_role("button", name="Delete Admin", exact=True).click()
        self.page.locator("#del-user").click()
        expect(self.page.locator("#del-error")).to_contain_text("last active administrator")
        expect(self.page.locator("#del-box")).to_be_visible()
        expect(self.page.locator("#del-user")).to_be_enabled()

    def test_busy_dialog_blocks_duplicate_submit_and_escape(self):
        self.open()
        self.hold_create = True
        self.fill_new_user()
        self.page.locator("#save-user").click()
        expect(self.page.locator("#save-user")).to_be_disabled()
        self.page.evaluate("document.querySelector('#edit-form').requestSubmit()")
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#edit-box")).to_be_visible()
        self.assertEqual(len(self.pending), 1)
        self.reply(self.pending[0], {**MEMBER, "id": 3}, 201)
        expect(self.page.locator("#edit-box")).not_to_be_visible()

    def test_access_control_and_expired_session(self):
        self.viewer = dict(MEMBER)
        self.page.goto(BASE + "/users.html")
        expect(self.page.locator("#access-status")).to_contain_text("Administrator access is required")
        expect(self.page.locator("#users")).to_be_hidden()
        self.assertFalse(any(call[1] == "/api/v1/user" for call in self.calls))
        self.failures[("GET", "/api/v1/user/me")] = (401, None)
        self.page.reload()
        expect(self.page).to_have_url(BASE + "/login.html")
        self.assertIsNone(self.page.evaluate("sessionStorage.getItem('vasteq.accessToken')"))

    def test_pagination_safe_text_and_mobile_dialog(self):
        self.records += [{**MEMBER, "id": number, "displayName": "<img src=x onerror=alert(1)>"} for number in range(3, 27)]
        self.open()
        expect(self.page.locator("#rows tr")).to_have_count(20)
        self.assertEqual(self.page.locator("#rows img").count(), 0)
        self.page.locator("#next").click()
        expect(self.page.locator("#list-status")).to_have_text("Showing 21–26 of 26 users")
        self.page.locator("#prev").click()
        expect(self.page.locator("#list-status")).to_have_text("Showing 1–20 of 26 users")
        for width in (320, 390, 768, 1280):
            self.page.set_viewport_size({"width": width, "height": 900})
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        self.page.set_viewport_size({"width": 320, "height": 700})
        self.page.locator("#add-user").click()
        bounds = self.page.locator("#edit-box").bounding_box()
        self.assertGreaterEqual(bounds["x"], 0)
        self.assertLessEqual(bounds["x"] + bounds["width"], 320)
        self.page.keyboard.press("Escape")
        expect(self.page.locator("#edit-box")).not_to_be_visible()
        expect(self.page.locator("#add-user")).to_be_focused()

    def test_list_failure_retry_and_admin_home_link(self):
        self.failures[("GET", "/api/v1/user")] = (0, None)
        self.page.goto(BASE + "/users.html")
        expect(self.page.locator("#retry-list")).to_be_visible()
        self.page.locator("#retry-list").click()
        expect(self.page.locator("#rows tr")).to_have_count(2)
        self.page.route("**/api/v1/station*", lambda route: self.reply(route, {"items": [], "total": 0}))
        self.page.goto(BASE + "/index.html")
        expect(self.page.get_by_role("link", name="Manage users")).to_be_visible()
        self.page.set_viewport_size({"width": 320, "height": 900})
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        self.page.get_by_role("link", name="Manage users").click()
        expect(self.page).to_have_url(BASE + "/users.html")
        self.viewer = dict(MEMBER)
        self.page.goto(BASE + "/index.html")
        expect(self.page.get_by_role("link", name="Manage users")).to_be_hidden()


if __name__ == "__main__":
    unittest.main()
