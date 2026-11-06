# The-Nepal-Cricket-Index

An independent cricket dashboard by [Howzat Analytics](https://howzatanalytics.com/) for exploring Nepal Premier League (NPL) and Nepal national-team data.

## Features

- NPL matches, scorecards, teams, players, season standings and statistics.
- Player comparisons with batting and bowling radar charts.
- Nepal national-team players, matches and tournament overviews.

Statistics reflect the available dataset and may not cover every match. NPL standings are derived from recorded league matches and are provisional when the season is incomplete.

## Local development

Requirements: Docker and Docker Compose, plus a copy of the cricket database at `data/nepal_cricket.db`. The database and parquet files are not included in this repository. For parquet imports or the full test suite, also provide the source files in `data/npl/` and `data/nepal/`.

1. Copy `.env.example` to `.env` and set a unique local `DJANGO_SECRET_KEY`. Never commit `.env` or use the example secret in production.
2. Start the development server:

   ```sh
   docker compose -f compose.development.yaml up --build
   ```

3. Open <http://localhost:8000>.

The development image copies local data and must not be published. Compose also mounts the project directory, so local changes are available in the container.

Run the application tests with:

```sh
docker compose -f compose.development.yaml run --rm --no-deps web python manage.py test cricket_nepal
```

### Rebuilding the cricket database

With the required parquet files in place, back up the existing database before rebuilding:

```sh
docker compose -f compose.development.yaml run --rm --no-deps web python scripts/import_parquet_to_sqlite.py
docker compose -f compose.development.yaml run --rm --no-deps web python scripts/import_nepal_parquet_to_sqlite.py
docker compose -f compose.development.yaml run --rm --no-deps web python scripts/add_nepal_abandoned_match.py
docker compose -f compose.development.yaml run --rm --no-deps web python scripts/add_npl_abandoned_match.py
docker compose -f compose.development.yaml run --rm --no-deps web python manage.py verify_cricket_database
```

The abandoned-match scripts must be run after the imports because the imports rebuild their respective tables.

## Production deployment

The production `Dockerfile` runs Gunicorn and does not include the cricket database. Copy the database to the server and mount it read-only at `/app/data/nepal_cricket.db`; it must be readable by the container's non-root user (UID 10001). For the production Compose configuration, set `CRICKET_DB_PATH` to the database's absolute path.

Provide a unique `DJANGO_SECRET_KEY`, set `DJANGO_DEBUG=false` and `DJANGO_SECURE_DEPLOYMENT=true`, and set `DJANGO_ALLOWED_HOSTS` to the public hostname. Keep the application port private behind a trusted HTTPS proxy that overwrites client-supplied `X-Forwarded-Proto` headers. The default Compose file is for production; `compose.development.yaml` is for local development only.

Run `python manage.py check --deploy` in the configured production container before making the site public. HSTS subdomains and preloading are intentionally not enabled; enable them only after confirming every affected subdomain is served exclusively over HTTPS.

## Data attribution

Match data is sourced from [Cricsheet](https://cricsheet.org/) and transformed and aggregated for this dashboard. See [Cricsheet licensing](https://cricsheet.org/licensing/) for the applicable licences. The national-team dataset contains no Afghanistan matches; Cricsheet explains its decision to withhold Afghan men's matches [here](https://cricsheet.org/article/explanation-for-withholding-of-afghanistani-matches/).
