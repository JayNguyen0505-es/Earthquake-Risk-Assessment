# Station API

Base endpoint: **`/api/v1/station`**. Requests and responses use JSON.
All endpoints require `Authorization: Bearer <JWT>` and an enabled account.
Admins, users, and guests can read stations. Only admins can create, update,
or delete them. Current account status and admin role are checked in the
database as well as the token.

| Method | Endpoint | Purpose | Access | Success |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/station` | List and search stations | Authenticated | 200 |
| GET | `/api/v1/station/{id}` | Get station details | Authenticated | 200 |
| POST | `/api/v1/station` | Create a station | Admin | 201 |
| PATCH | `/api/v1/station/{id}` | Update station metadata | Admin | 200 |
| DELETE | `/api/v1/station/{id}` | Delete a station without linked channels | Admin | 204 |

## List filters

| Query parameter | Meaning |
| --- | --- |
| `offset` | Nonnegative row offset; default 0 |
| `limit` | Page size from 1 to 100; default 20 |
| `networkCode` | Match a network code |
| `stationCode` | Match a station code |
| `province` | Match a province |
| `city` | Match a city |
| `hasCoordinates` | `true` for known latitude/longitude; `false` for missing coordinates |
| `search` | Case-insensitive substring search in station names |

Filters combine with AND. Blank text filters are ignored. Codes retain their
case and follow the database's case-sensitive code comparison. Search treats
`%` and `_` as literal characters. Results are ordered by `id` ascending.

The list response contains `items`, `total` (count matching all filters),
`offset`, and `limit`. An empty page returns an empty `items` array.

## Fields

| JSON field | Required on creation | Limits / meaning |
| --- | --- | --- |
| `networkCode` | Yes | 1–2 printable ASCII characters without spaces |
| `stationCode` | Yes | 1–5 printable ASCII characters without spaces |
| `name` | No | Station name, maximum 120 characters |
| `city` | No | Maximum 120 characters |
| `province` | No | Maximum 120 characters |
| `instrumentType` | No | Maximum 64 characters |
| `instrumentSerial` | No | Text, maximum 64 characters; preserves leading zeros |
| `coordinateCrs` | No | Source coordinate reference system, maximum 64 characters |
| `latitude` | No | −90 to 90 degrees, at most 6 decimal places |
| `longitude` | No | −180 to 180 degrees, at most 6 decimal places |
| `elevationM` | No | Meters, at most 7 integer digits and 3 decimal places |
| `metadataUri` | No | Source metadata location, maximum 1024 characters |
| `metadataSource` | No | Provenance description, maximum 255 characters |

Text values are trimmed. The `(networkCode, stationCode)` pair must be unique.
Latitude and longitude must both be present or both be `null`. Unknown
coordinates and CRS remain `null`; no coordinates or datum are inferred.
Metadata locations are stored as references, not fetched by these endpoints.

Responses include all fields above plus `id`, `createdAt`, and `updatedAt`.
Timestamps use UTC. POST returns a `Location` header pointing to the new station.

Example creation body:

```json
{
  "networkCode": "VN",
  "stationCode": "4001",
  "name": "Example station",
  "province": "Sơn La",
  "instrumentType": "Palert",
  "instrumentSerial": "00123",
  "latitude": null,
  "longitude": null
}
```

PATCH accepts a nonempty JSON object containing only writable fields. Omitted
fields are preserved; explicit `null` clears optional fields. Required codes
cannot be cleared. The resulting station must satisfy all validation rules.
To remove coordinates, send `{"latitude":null,"longitude":null}`. `id` and
timestamps cannot be changed. Unknown fields are rejected.

DELETE removes the station record. Linked channels block deletion, preserving
channel and phase-pick references. It does not delete channels or waveform files.

## Errors

| Status | Meaning |
| --- | --- |
| 400 | Invalid fields, coordinate pair, update object, or pagination |
| 401 | Missing/invalid JWT, nonexistent account, or disabled account |
| 403 | Non-admin write attempt |
| 404 | Station not found |
| 409 | Duplicate codes (`station_exists`) or linked channels (`station_in_use`) |

Application errors contain `code` and `message`. Framework authentication and
validation errors may use a different response body.
