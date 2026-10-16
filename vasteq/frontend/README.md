# VAST-Earthquake frontend

The public landing page is available at `/` and `/index.html`. Account pages
are available at `/register.html`, `/login.html`, and `/account.html`.
They use the local SB Admin 2 Bootstrap stylesheet from `templates/sbadmin2.zip`,
a small Material-style CSS override, system fonts, and vanilla JavaScript.
There are no CDN requests, JavaScript frameworks, or frontend build tools.
The template's MIT license is included beside the vendor stylesheet. The station
map also uses a local copy of Leaflet 1.9.4 with its BSD license.

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

## Shared includes

nginx renders SSI includes from `public/inc/`: `head.html`, `brand.html`,
`header.html`, `caption.html`, and `submit.html`. Each page sets `page` to its
JavaScript module name before including the shared head. Login and registration
use `auth`; each sets `submit` for the shared button label.

```html
<!--#set var="page" value="users" -->
<!--#include virtual="/inc/head.html" -->
```

JavaScript logic stays in ES modules; SSI shares the module script tag.
Management pages also share `admin-nav.html`, `actions.html`, and `pager.html`.
Station management and the map share `station-filters.html`.
Includes are internal to nginx and cannot be opened directly. Edit a partial
once to update every page that includes it. HTML changes need no reload;
nginx configuration changes require validation and a reload or container recreation.

Serve the frontend through nginx on port 28080. Quarkus static serving on port
8080 and `file://` do not expand SSI. The backend continues to serve the API on
8080; nginx proxies it under the frontend origin. See the
[backend README](../backend/README.md) for backend setup.

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

## Station management

Admins can open `/stations.html` from **Manage stations** on the home page or
the administration tabs. The table shows ID, network/station code, name,
province, latitude, longitude, and Material edit/delete icons. Search by name,
filter by province or coordinate availability, and page through the results.
The province field accepts any province, with suggestions for the study area.

Add/edit dialogs include all station metadata. Network and station codes are
required; optional blank fields are saved as `null`. Coordinates must be entered
or cleared together. Unknown coordinates display as `—`; the CRS is never
assumed. Instrument serial numbers retain leading zeros.

Deletion requires confirmation and permanently removes the station. The API
blocks deletion when channels reference it. Success and error toasts, inline
errors, and retry controls follow the user-management page.

## Station map

Signed-in users can open `/map.html` from **Station map** on the home page.
Admins also have a **Map** tab in the administration navigation. The page uses
[Leaflet 1.9.4](https://leafletjs.com/download.html), served locally from
`public/assets/vendor/leaflet/`, and OpenStreetMap raster tiles with visible
[attribution](https://operations.osmfoundation.org/policies/tiles/).
The basemap needs internet access; station markers remain usable if tiles fail.

Name, province, and coordinate filters match station management. The page reads
all matching API pages, 100 records at a time, and fits the map to their locations.
Select a marker or use **Go to station** to view its name, province, city,
coordinates, elevation, CRS, and instrument. **Fit stations** restores the full
view; **Refresh** reloads metadata after changes while preserving filters.

Missing coordinates are counted and never plotted at a substitute location.
Zero coordinates are valid. Coordinates are displayed as reported, without
datum conversion, and an unspecified CRS is flagged in the summary and popup.
No station metadata is changed. The map calls the existing authenticated read
API; adding, editing, and deleting stations remain administrator actions.

## API client

`public/assets/js/api.js` follows the reusable `Api` and endpoint-specific class
structure from `templates/api.js`. It uses the current backend's raw JSON
responses and HTTP status codes, handles empty 204 responses, reports request
errors, and applies a 15-second timeout. Protected calls can read a JWT from
`sessionStorage` under `vasteq.accessToken`. Registration and login omit bearer
tokens. Request bodies and tokens are not logged.

The original sample and template archive remain in `templates/`; they are not
published as static resources. No database schema changes are needed.

## Code style

Use short, clear names such as `load`, `edit`, `data`, and `err`. Keep markup in
HTML, share small helpers in `ui.js`, and use `auth.js` for both account forms.
Avoid runtime assertions, response-shape checks, and unused abstractions. Keep
input validation, request errors, access controls, and accessible labels.
Vendor files stay as distributed.

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
`tests/test_stations.py` adds nine checks for station CRUD, filters, coordinate
validation, linked-channel conflicts, pagination, access control, and mobile layout.
`tests/test_map.py` checks loading every API page, filters, missing and zero
coordinates, safe popup text, keyboard selection, tile failures, session access,
retries, navigation, and mobile layout. API calls and map tiles are intercepted;
these tests neither change station records nor download external tiles.

With nginx and the backend running, install Playwright in a separate testing environment
and run from the repository root:

```sh
python -m pip install playwright
python -m playwright install chromium
python -m unittest discover -s vasteq/frontend/tests -v
```

Tests use `http://127.0.0.1:28080` by default. Set `VASTEQ_FRONTEND_URL` to test another nginx host. Playwright is a test-only tool;
it is not shipped to frontend users.
