# User API

All endpoints use the prefix **`/api/v1/user`**. The base endpoints below use
the prefix itself, without an additional path segment.

| Method | Endpoint | Purpose | Access |
| --- | --- | --- | --- |
| POST | `/register` | Register an account | Public |
| POST | `/login` | Authenticate and obtain a JWT | Public |
| GET | `/me` | Get your account details | Authenticated |
| PATCH | `/me` | Update your email or display name | Authenticated |
| PUT | `/me/password` | Change your password | Authenticated |
| GET | Base endpoint | List accounts with `offset` and `limit` | Admin |
| POST | Base endpoint | Create an account and assign its role | Admin |
| GET | `/{id}` | Get account details | Admin |
| PATCH | `/{id}` | Update email, name, role, or enabled status | Admin |
| DELETE | `/{id}` | Disable an account | Admin |

Protected endpoints require `Authorization: Bearer <JWT>`. Deletion disables
the account while preserving its database record.

Health check: **`GET /q/health/ready`**.

See the [backend README](../backend/README.md) for request fields, responses,
configuration, and administrator setup.
