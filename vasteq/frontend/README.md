# VAST-Earthquake frontend

The public landing page is available at `/` and `/index.html`. Account pages
are available at `/register.html`, `/login.html`, and `/account.html`.
They use the local SB Admin 2 Bootstrap stylesheet from `templates/sbadmin2.zip`,
a small Material-style CSS override, system fonts, and vanilla JavaScript.
There are no CDN requests, JavaScript frameworks, or frontend build tools.
The template's MIT license is included beside the vendor stylesheet.

## Serve with nginx

The nginx Docker service serves `public/` at `http://localhost:28080/` and
proxies `/api/` to the Java backend on `127.0.0.1:8080`. Start the backend first,
then run from the repository root:

```sh
docker compose -f vasteq/deployment/compose.yaml up -d --wait nginx
```

See the [deployment instructions](../deployment/README.md#frontend-with-nginx)
for configuration validation and reload commands. This Linux setup uses Docker
host networking. Frontend edits are served directly without rebuilding Maven.

## Serve directly with the backend

Frontend files live in `public/`. Maven includes this directory in Quarkus's
static resources, so the page and API share an origin:

```sh
cd vasteq/backend
./mvnw package
python3 scripts/run.py
```

Open `http://127.0.0.1:8080/`. See the
[backend README](../backend/README.md) for database and signing-key setup.
Rebuild after changing frontend files to update the packaged application.
Opening the HTML directly through `file://` does not support module scripts or
API calls. A separate static host would need to proxy `/api/` to the backend.

## Landing page

The public home page introduces the project, its capabilities, the three study
provinces, and project information. Analysis and risk-assessment cards are
explicitly marked as in development. The decorative waveform SVG is an
illustration, not a recording or a map.

Visitors can read the page without authentication or JavaScript. Station
records remain authenticated, matching the backend permissions. After session
verification, the page shows My account and Sign out and loads a preview of
three stations with the actual inventory count. Unknown coordinates are marked
as pending. Errors offer retry controls; an expired token restores the public
view. Sign out clears the local session without leaving the landing page.

## Registration

The form collects display name, email, password, and password confirmation.
It calls `POST /api/v1/user/register` with only `displayName`, `email`, and
`password`. Confirmation is checked in the browser. The backend assigns role
`user`; account creation does not automatically log in or store a JWT.

The page provides inline field validation, password visibility toggles,
loading feedback, duplicate-email errors, network-error feedback, and a
success state. Labels, keyboard focus, and live status messages support
accessible use. Layout adapts to mobile screens and reduced-motion preferences.

## Login and session

`/login.html` collects email and password and calls `POST /api/v1/user/login`.
It provides field validation, password visibility, loading feedback, and
credential/network errors. Failed attempts preserve the entered values.
On success, only the JWT is stored in `sessionStorage` as `vasteq.accessToken`;
passwords are never stored or logged. If browser storage is unavailable,
the page reports the failure and permits another attempt.

Successful login opens `/index.html`, the public landing page. It checks the
session through `GET /api/v1/user/me` before displaying account controls.
My account opens `/account.html`, which shows the display name and email.
On the account page, missing or rejected tokens return to login; temporary connection errors allow
retrying. Sign out removes the local token and returns to login. Tokens still
expire according to the backend's configured lifetime, without server-side
revocation. The full application dashboard is a later frontend step.

## User management

Administrators can open `/users.html` through the **Manage users** link on the
home page. The page verifies the current account before fetching the paginated
user table. Regular users cannot access the management controls; the backend
also enforces administrator permissions on every management request.

The table displays ID, name, email, and Edit/Delete buttons, with an Add user
button above the table on the right. Add and edit use native modal dialogs with
Bootstrap and Material styling. Creation collects name, email, password, and
role; passwords follow the existing API's 12–128 character requirement. Editing
allows changing name, email, role, and enabled status, without changing passwords.
Deletion requires a confirmation dialog and uses the existing API's soft delete:
the account becomes disabled, its record remains visible, and editing can enable
it again. The last active administrator is protected by the backend.

Success and failure notifications appear at the top right. Failed operations
preserve the dialog values and show an inline error for correction or retry.
The page supports keyboard focus, Escape to cancel, duplicate submission
protection, empty/loading/error states, and a scrolling table on small screens.
It uses vanilla JavaScript and native `<dialog>` elements, with no additional
runtime libraries.

## API client

`public/assets/js/api.js` follows the reusable `Api` and endpoint-specific class
structure from `templates/api.js`. It uses the current backend's raw JSON
responses and HTTP status codes, handles empty 204 responses, reports request
errors, and applies a 15-second timeout. Protected calls can read a JWT from
`sessionStorage` under `vasteq.accessToken`. Registration and login omit bearer
tokens. Request bodies and tokens are not logged.

The original sample and template archive remain in `templates/`; they are not
published as static resources. No database schema changes are needed.

## Browser tests

`tests/test_registration.py` contains seven browser checks for registration validation,
request payloads, duplicate submission protection, errors and retries,
password controls, keyboard focus, and responsive layout. Tests intercept
registration requests and create no database accounts. `tests/test_login.py`
adds nine checks for login validation, token storage, error handling, home
session verification, sign out, and mobile layout. Both suites use intercepted
API responses. `tests/test_home.py` adds eight checks for public access,
authenticated station previews, session failures, retries, sign-out races,
and responsive navigation. `tests/test_users.py` adds nine checks for admin
access, CRUD dialogs, notifications, retries, pagination, duplicate submission
protection, and mobile layout, also without writing database records.

With the backend running, install Playwright in a separate testing environment
and run from the repository root:

```sh
python -m pip install playwright
python -m playwright install chromium
python -m unittest discover -s vasteq/frontend/tests -v
```

Set `VASTEQ_FRONTEND_URL` to test another host. Playwright is a test-only tool;
it is not shipped to frontend users.
