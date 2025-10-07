# Astro CLI Deployment

This directory contains configuration templates for deploying Apache Airflow using the [Astro CLI](https://www.astronomer.io/docs/astro/cli/install-cli) (Astronomer distribution). This deployment method is recommended for local development on macOS or Windows.

## Overview

The Astro CLI deployment uses:
- **PostgreSQL/TimescaleDB**: Installed locally for the analytics database (`lens`).
- **Astro CLI + Docker Desktop**: Runs Airflow in containers.
- **Containerized PostgreSQL**: Airflow's metadata database (separate from analytics database).
- **Port 5433**: For Airflow metadata database to avoid conflict with analytics database on port 5432.

## Prerequisites

Before setting up Astro CLI, ensure you have:

1. **PostgreSQL or TimescaleDB** installed and running locally
   - Analytics database (`lens`) must be initialized.
   - See [Database Installation and Initialization](../../README.md#database-installation-and-initialization).

2. **Astro CLI** installed
   - macOS: `brew install astro`.
   - Other: See [Astro CLI installation docs](https://www.astronomer.io/docs/astro/cli/install-cli).

3. **Docker Desktop** installed and running
   - Required for Astro CLI to run Airflow containers

## Setup Instructions

Navigate to the repository root and follow these steps:

### 1. Initialize Astro Project

```bash
cd /path/to/openetl
astro dev init
```

This creates:
- `.astro/` directory with configuration.
- `Dockerfile` with Astronomer Runtime base image.
- `.dockerignore` file.
- `airflow_settings.yaml` for Airflow configuration.
- `packages.txt` for system packages.
- `plugins/` directory for Airflow plugins.

### 2. Copy Configuration Template

```bash
cp iac/astro_cli_docker/config.yaml.template .astro/config.yaml
```

This sets:
- Metadata database port to `5433` (avoids conflict with analytics database).
- Project name to `openetl`.

### 3. Copy Docker Compose Override

```bash
cp iac/astro_cli_docker/docker-compose.override.yml.template docker-compose.override.yml
```

This configures essential volume mounts and environment variables for:
- Database credentials directory (`SQL_CREDENTIALS_DIR`).
- Pipeline data directory (`DATA_DIR`).
- Custom files for data processing.

### 4. Set Up Environment Variables

```bash
cp iac/astro_cli_docker/.env.template .env
```

Edit the `.env` file and configure at minimum:

```bash
SQL_CREDENTIALS_DIR=/absolute/path/to/your/sql_credentials
```

> **Important:**
> - Use absolute paths (Docker Compose does NOT expand `~`).
> - `SQL_DB_HOST` defaults to `host.docker.internal` (works on Docker Desktop for Mac/Windows).
> - `DATA_DIR` defaults to `{repo_root}/data/` if not set.

See [`.env.template`](.env.template) for all available configuration options.

### 5. Create Data Directory

```bash
mkdir -p data
```

This directory stores pipeline data organized by state (ingest, process, store, quarantine). Creating it manually ensures correct file permissions.

### 6. Start Astro

Export environment variables and start Astro:

```bash
export $(cat .env | grep -v "^#" | grep -v "^$" | xargs)
astro dev start
```

> **Important:** You must export `.env` variables before **each** `astro dev start` to enable Docker Compose variable substitution in volume mounts.

Airflow will be accessible at:
- **Webserver**: http://localhost:8080
- **Default credentials**: admin / admin

## Configuration Files

### config.yaml

Located at `.astro/config.yaml` after setup. Configures:
- Metadata database port (`5433`).
- Project name.
- Other Astro-specific settings.

### .env

Environment variables for Airflow and pipeline execution:
- `SQL_CREDENTIALS_DIR`: Path to database credential JSON files (required).
- `SQL_DB_HOST`: Analytics database host (default: `host.docker.internal`).
- `DATA_DIR`: Pipeline data storage directory (default: `{repo_root}/data/`).
- `TEST_DB_URL`: Test database connection string (optional).

### docker-compose.override.yml

Configures Docker Compose environment variables and volume mounts:
- `SQL_CREDENTIALS_DIR` volume mount for database credentials
- `DATA_DIR` volume mount for pipeline data
- `~/.garminconnect` volume mount for Garmin authentication tokens
- Environment variables passed to Airflow containers

This file is created in step 3 of the setup instructions and is required for the deployment to function properly.

## Updating Deployments

The update procedure varies based on what changed:

### When to Restart Astro

Use `astro dev restart` for:
- Changes to `.env` file (environment variables).
- Changes to `config.yaml` (Airflow configuration).
- Changes to `docker-compose.override.yml` (volume mounts, container settings).

```bash
astro dev restart
```

### When to Rebuild Astro

Use `astro dev stop && astro dev start` for:
- Changes to `requirements.txt` (new Python packages).
- Changes to `packages.txt` (new system packages).
- Changes to DAG code or Python modules.

```bash
astro dev stop
astro dev start
```

> **Note:** Astro CLI automatically detects changes to `requirements.txt` and rebuilds the Docker image during `astro dev start`.

## Stopping Astro

To stop all Airflow containers:

```bash
astro dev stop
```

To stop and remove all containers and volumes:

```bash
astro dev kill
```

## Troubleshooting

**Port conflicts:**
- If port 8080 is already in use, modify `webserver.port` in `.astro/config.yaml`.
- If port 5433 is already in use, modify `postgres.port` in `.astro/config.yaml`.

**Database connection issues:**
- Verify `SQL_CREDENTIALS_DIR` is set and contains valid credential files.
- Ensure PostgreSQL is running on the host.
- Check `SQL_DB_HOST` in `.env` is correct for your platform.

**Volume mount issues:**
- Ensure you exported `.env` variables before `astro dev start`.
- Use absolute paths in `.env` (no `~` expansion).
- Verify the `data/` directory exists.

**Container issues:**
- Run `astro dev logs` to view container logs.
- Run `docker ps` to verify containers are running.
- Try `astro dev kill && astro dev start` for a clean restart.

## Additional Resources

- [Astro CLI Documentation](https://www.astronomer.io/docs/astro/cli/overview).
- [Astronomer Runtime](https://www.astronomer.io/docs/astro/runtime-release-notes).
- [Main Project README](../../README.md).
