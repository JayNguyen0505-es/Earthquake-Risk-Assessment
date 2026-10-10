# VAST-Earthquake full stack system

This directory will contain the integrated web system for earthquake risk
assessment and decision support in Sơn La, Điện Biên, and Lai Châu, Northwest
Vietnam. It connects the research models developed in work packages
[5.1.1](../511/README.md) and 5.1.2 with data management and WebGIS visualization.

The system supports work package 5's automated risk assessment and work package
6's earthquake response and damage reduction workflows. The complete project
proposal is in [docs/proposal.pdf](../docs/proposal.pdf).

## Planned technology stack

| Component | Technology | Responsibility |
| --- | --- | --- |
| Frontend | Vanilla HTML, JavaScript, CSS, Bootstrap | User interface, forms, charts, and WebGIS views |
| Backend | Java, Quarkus | REST APIs, authentication, authorization, data management, and model orchestration |
| Database | MySQL | Users, station metadata, events, model runs, and assessment results |
| Model services | Python, FastAPI | Serve trained models from work packages 5.1.1 and 5.1.2 |

The frontend calls the backend through REST APIs. The backend manages database
access and invokes the model services, which return predictions and associated
model metadata for storage and visualization.

## Planned capabilities

- JWT authentication and role-based access for administrators, users, and guests.
- User management and permissions enforced by the backend.
- Station inventory, waveform information, and seismic event management.
- WebGIS views of station locations, earthquakes, and assessment layers.
- Forms to enter model parameters, launch inference, and inspect run status and
  results, including model versions and uncertainty when available.
- Integration of earthquake parameter estimation from 5.1.1 and ground-shaking
  prediction from 5.1.2.
- Risk scenarios and decision support workflows, to be specified under work
  package 6.

## Intended source layout

```text
vasteq/
  frontend/        Web interface and static assets
  backend/         Quarkus application
  model-services/  FastAPI inference applications
  deployment/      Local development and deployment configuration
```

The MySQL [deployment setup](deployment/README.md) is available, with a
[approved eight-table database structure](backend/database/README.md). The [backend account API](backend/README.md) implements registration, JWT login,
and account management using Hibernate ORM and MySQL JDBC. Frontend and model
services will be added as implementation continues.
Research and training code remain in their respective work package directories.
Shared raw data remains in `../data/` and must not be duplicated here.

## Initial implementation scope

Start with the application structure, authentication and user management, station
and event APIs, and the WebGIS interface. Define model-service API contracts so
trained models can be connected as they become available.

Station coordinates and instrument metadata are pending from the data provider.
Until supplied, station records must retain an explicit missing-coordinate state;
map views must not assign fabricated coordinates. Model services and assessment
views must clearly identify unavailable models and any demonstration results.
See the [sample metadata audit](../docs/511-sample-metadata.md) for current data
limitations.
