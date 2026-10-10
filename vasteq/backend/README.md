# VAST-Earthquake backend

Java 21+, Quarkus, Hibernate ORM with Panache, and MySQL Connector/J through
Quarkus JDBC. The application uses the approved `users` and `stations` tables. Hibernate does
not create or change the production schema; apply the deployment SQL first.

## Start locally

Requires OpenJDK 21 or newer, Python 3, OpenSSL, and the existing MySQL Docker
service. From this directory:

```sh
python3 scripts/setup_keys.py
./mvnw package
python3 scripts/run.py
```

The API listens on `http://127.0.0.1:8080`. Health is at `/q/health/ready`.
The launcher reads the application password from
`../deployment/.secrets/mysql_app_password` and signing keys from `.secrets/`.
Generated keys and build outputs are ignored by Git. Keep the entire
`target/quarkus-app` directory when deploying the packaged application.

Configuration overrides: `DB_URL`, `DB_USER`, `DB_PASSWORD`, `JWT_PRIVATE_KEY`,
`JWT_PUBLIC_KEY`, `JWT_ISSUER`, `QUARKUS_HTTP_HOST`, and `QUARKUS_HTTP_PORT`.
Key locations can be file URIs. JWT lifetime defaults to 900 seconds and can be
changed with `VASTEQ_JWT_TTL_SECONDS`. Database timestamps use UTC.

Create the first administrator against the local Docker database:

```sh
python3 scripts/bootstrap_admin.py --email admin@example.com --name Administrator
```

The script prompts for a password and creates an administrator only when none
is enabled (`administrators_created` is 1 on creation, 0 otherwise). Use an
unused email address. Subsequent administrators are created through the API.
No default administrator or password is included.

## Account API

All routes use `/api/v1/user`. Request and response bodies are JSON. Protected
routes require `Authorization: Bearer <accessToken>`.

| Method | Route | Access | Behavior |
| --- | --- | --- | --- |
| POST | `/register` | Public | Register an enabled account with role `user`; returns 201 |
| POST | `/login` | Public | Return a signed JWT and account details |
| GET | `/me` | Signed in | Read own account |
| PATCH | `/me` | Signed in | Update own email or display name |
| PUT | `/me/password` | Signed in | Change password; returns 204 |
| GET | base route | Admin | List accounts with `offset=0&limit=20` (maximum limit 100) |
| POST | base route | Admin | Create an account; returns 201 |
| GET | `/{id}` | Admin | Read an account |
| PATCH | `/{id}` | Admin | Update email, display name, role, or enabled state |
| DELETE | `/{id}` | Admin | Disable an account; returns 204 |

Registration and login examples:

```sh
curl -X POST http://127.0.0.1:8080/api/v1/user/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"example-password-123","displayName":"Example User"}'
curl -X POST http://127.0.0.1:8080/api/v1/user/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com","password":"example-password-123"}'
```

Login returns `accessToken`, `tokenType` (`Bearer`), `expiresIn` (seconds), and
`user`. User objects contain `id`, `email`, `displayName`, `role`, `enabled`,
`createdAt`, and `updatedAt`; password hashes are never returned. Lists return
`items`, `total`, `offset`, and `limit`.

Profile updates accept `email` and/or `displayName`. Password changes require
`currentPassword` and `newPassword`. Admin creation takes the registration
fields and an optional `role` (`admin`, `user`, or `guest`, default `user`).
Admin updates also accept `role` and `enabled`. Empty updates are rejected.
Emails are trimmed and lowercased. New passwords must be 12–128 characters.
Passwords use salted PBKDF2-SHA256; there is no password reset or email
verification flow.

Invalid requests return 400; invalid credentials, expired tokens, or disabled
accounts return 401; insufficient permissions return 403; missing accounts
return 404; duplicate emails and attempts to disable or demote the last active
administrator return 409. Application errors contain `code` and `message`.
Framework authentication and validation errors may use a different body.

Deletion disables accounts to preserve references from model runs. Protected
requests check current account status and admin permissions in the database.
JWTs expire naturally: there is no token revocation table, refresh endpoint,
or logout endpoint. Changing a password does not invalidate existing JWTs.
After a role change, log in again to obtain updated role claims.

## Station API

Station management is available at `/api/v1/station`, with authenticated reads
and admin-only creation, updates, and deletion. See the
[station API reference](../deployment/api-station.md) for endpoints, filters,
fields, and coordinate validation.

## Tests

```sh
./mvnw test
```

API tests use an isolated in-memory H2 database in MySQL compatibility mode.
They cover registration, validation, login, JWT checks, own-profile and password
changes, admin management, and last-administrator protection. Station tests
cover read/write permissions, filtering, pagination, coordinate validation,
partial updates, duplicate codes, and deletion restricted by linked channels. The PEM files in
`src/test/resources` are test fixtures only; local runtime keys are generated
separately by `setup_keys.py`.
