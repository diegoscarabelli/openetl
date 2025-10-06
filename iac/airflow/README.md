# Apache Airflow

[Apache Airflow](https://airflow.apache.org/) is an open-source platform for programmatically authoring, scheduling, and monitoring workflows. Workflows are defined as Directed Acyclic Graphs (DAGs), specifying the execution order of tasks.

This directory provides deployment configuration for running Airflow version 3.x on Ubuntu/Linux servers using Docker Compose.

## Prerequisites

Before you begin, ensure the following:

1. **Platform**: Ubuntu/Linux server (this deployment is not compatible with macOS).
2. **Docker Engine**: Install Docker Engine and Docker Compose as described in the [docker_install.sh](docker_install.sh) script. After installation, log out and log back in for group membership changes to take effect.
3. **PostgreSQL**: PostgreSQL must be installed and running on the same server. This deployment uses a colocated database architecture where the Airflow metadata database runs on the same PostgreSQL instance as the analytics database.
4. **Repository**: Clone this repository to the target server to facilitate deployment.

## Configuration and Initialization

The installation uses these key files:

- [`airflow_install.sh`](airflow_install.sh): Automates the build and deployment of a custom Airflow Docker image, following the [official guidelines](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html#using-custom-images).
- [`docker-compose.yaml`](docker-compose.yaml): Based on the [official Airflow Docker Compose](https://airflow.apache.org/docs/apache-airflow/3.1.0/docker-compose.yaml) configuration, customized for this deployment. The accompanying [`Dockerfile`](Dockerfile) builds the image for the specified Airflow version.
- `.env`: Defines environment variables for Airflow and pipeline configuration.
- [`airflow_db.ddl`](airflow_db.ddl) and [`airflow_db_grants.ddl`](airflow_db_grants.ddl): Create the Airflow metadata database and configure permissions.

Review the [changelog](https://airflow.apache.org/docs/apache-airflow/stable/release_notes.html) for your target Airflow version to ensure compatibility and identify any breaking changes.

Before running the automated installation script, complete the following configuration steps in order:

1. **Environment variables**: Configure `.env` with paths and connection settings.
2. **Database setup**: Initialize the Airflow metadata database using the provided DDL scripts.
3. **Resource allocation**: Adjust compute resources in `docker-compose.yaml` based on your hardware.
4. **Admin credentials**: Customize the admin user details in `airflow_install.sh`.

### Environment Configuration

Before installing Airflow, configure the environment variables in `iac/airflow/.env`.

> **Important:** Docker Compose does NOT expand `~` (tilde) in environment variables. All paths in the `.env` file must be absolute paths (e.g., `/home/username/path`), not relative paths with `~`.

> **Note:** The data directory defaults to `~/airflow/data/`. Set the `DATA_DIR` environment variable in `.env` to customize this location.

The `.env` file will be copied to `~/airflow/.env` by the `airflow_install.sh` script, which will also append `AIRFLOW_UID` and `AIRFLOW_GID` automatically.

### Metadata Database Setup

This deployment uses a colocated database architecture where both the Airflow metadata database and analytics database run on the same PostgreSQL instance.

#### Database Architecture

- **Airflow metadata database (`airflow_db`)**: Stores Airflow's operational data (DAG runs, task instances, users, etc.).
- **Analytics database (`lens`)**: Stores application data processed by pipelines.
- **Default connection**: Both databases are accessible via Docker bridge network at `172.17.0.1:5432`.
- **Benefit**: Minimizes infrastructure overhead for single-server deployments.
- **Customization**: Set `SQL_DB_HOST` in `.env` to point to a remote database server if needed.

The IP address shown (typically `172.17.0.1`) is the Docker bridge network gateway, which acts as the host's address from the perspective of containers. When Airflow containers need to connect to PostgreSQL running on the host machine, they use this gateway IP instead of `localhost`, since `localhost` inside a container refers to the container itself, not the host. This gateway IP is already configured as the default `SQL_DB_HOST` value in the environment configuration.

On Ubuntu/Linux with Docker Engine (as opposed to Docker Desktop), the special DNS name `host.docker.internal` is not available. Docker Engine does not provide this convenience hostname, so you must use the bridge network gateway IP directly. To determine your system's Docker bridge gateway IP address:

```bash
ip addr show docker0
```

#### Database Creation and Permissions

Create the Airflow metadata database and user by running [airflow_db.ddl](airflow_db.ddl):

```bash
# Connect to the default postgres database
psql -U postgres -d postgres -f airflow_db.ddl

# Alternative with TCP/IP and password authentication
psql -h localhost -U postgres -d postgres -f airflow_db.ddl
```

> **Important:** Before running this script, replace the `<REDACTED>` password placeholder with your actual password for the `airflow` user.

This script creates:
- `airflow_db` database.
- `airflow` user with full privileges on `airflow_db`.
- `readers` role for read-only analytics access.
- Security restrictions on backend control functions.

After creating the database, configure permissions within `airflow_db` by running [airflow_db_grants.ddl](airflow_db_grants.ddl):

```bash
# Connect to the airflow_db database (not postgres)
psql -U postgres -d airflow_db -f airflow_db_grants.ddl

# Alternative with TCP/IP and password authentication
psql -h localhost -U postgres -d airflow_db -f airflow_db_grants.ddl
```

This script sets up:
- Full privileges for the `airflow` user on the public schema.
- Default privileges for future objects created by `airflow`.
- Read-only permissions for the `readers` role.

For more details on setting up a PostgreSQL backend, see the [documentation](https://airflow.apache.org/docs/apache-airflow/stable/howto/set-up-database.html#setting-up-a-postgresql-database).

### Compute Resources

Optimize Airflow performance by configuring resource limits in [`docker-compose.yaml`](docker-compose.yaml):

**Worker Memory Limit**
Set the memory limit under `deploy.resources.limits.memory` for the `airflow-worker` service to approximately 50% of total server RAM. This prevents resource exhaustion while maintaining efficient task execution.

Example for a 64GB server:
```yaml
airflow-worker:
  deploy:
    resources:
      limits:
        memory: 32G
```

**Celery Worker Autoscale**
Configure `AIRFLOW__CELERY__WORKER_AUTOSCALE` to define the maximum and minimum number of concurrent worker processes. The format is `<max>,<min>`. 

Set the maximum based on your server's vCPU count and expected workload intensity. The total memory allocated to the worker container is split among all active worker processes. With a 32G memory limit and 10 concurrent workers, each worker receives approximately 3.2G of memory. Consider your tasks' memory requirements when setting the maximum worker count. Memory-intensive data processing tasks may require fewer concurrent workers to avoid out-of-memory errors.

To determine your server's vCPU count:
```bash
nproc
```

Example for a 24-vCPU server with moderate workload:
```yaml
AIRFLOW__CELERY__WORKER_AUTOSCALE: '10,1'
```

Adjust these settings based on your hardware specifications, expected workload, and task memory requirements.

### Airflow Admin User 

Before running the installation script, customize the admin user credentials in `airflow_install.sh`:

```bash
docker compose exec airflow-scheduler airflow users create \
    --username airflow \
    --firstname YourFirstName \
    --lastname YourLastName \
    --role Admin \
    --email your.email@example.com \
    --password <REDACTED_PASSWORD>
```

Replace `YourFirstName`, `YourLastName`, `your.email@example.com`, and `<REDACTED_PASSWORD>` with your actual admin user details.

## Installation

After completing the environment configuration, database initialization, and admin user customization, run the installation script from the `iac/airflow` directory:

```bash
bash airflow_install.sh
```

The installation script performs the following steps:

1. Creates `~/airflow` directory structure including `logs/` subdirectory.
2. Copies `iac/airflow/.env` to `~/airflow/.env` and appends `AIRFLOW_UID` and `AIRFLOW_GID` for proper file permissions.
3. Copies [`docker-compose.yaml`](docker-compose.yaml), [`Dockerfile`](Dockerfile), and `requirements.txt` to `~/airflow`.
4. Initializes the Airflow database schema using `docker compose up airflow-init --build`.
5. Starts all Airflow services with `docker compose up --force-recreate -d`.
6. Creates the admin user for web UI access.

## Authentication

Airflow 3.x supports two authentication managers:

**Flask AppBuilder (FAB) Authentication Manager** (Recommended)
- Stores user credentials persistently in the metadata database
- Allows CLI-based user management
- Ensures consistent admin access across container restarts
- Configured in [docker-compose.yaml](docker-compose.yaml) by setting the `AIRFLOW__CORE__AUTH_MANAGER` environment variable

**Simple Auth Manager** (Default)
- Creates temporary admin credentials that change when containers are recreated
- Credentials are logged in the `apiserver` container logs
- Not suitable for production use due to credential rotation

This deployment uses the FAB Authentication Manager to provide persistent, reliable admin access to the Airflow web UI. The admin user created during installation is stored in the metadata database and remains consistent across deployments.

## Deployment Updates

The Docker image must be rebuilt when infrastructure components change.

**When to rebuild Docker images:**
- Changes to `requirements.txt` (new Python packages)
- Changes to `Dockerfile` (image configuration)
- To ensure completely fresh images

**When rebuilding is not needed:**
- Environment variable changes in `.env`
- Configuration updates in `docker-compose.yaml` (without new dependencies)
- DAG or Python module changes (automatically mounted)

The `--force-recreate` flag applies environment variable updates from `docker-compose.yaml` without rebuilding the image, which is faster for configuration-only changes.

To rebuild the image and apply changes, run the following in `~/airflow`:

```bash
docker compose down
docker system prune -f
docker compose build --no-cache
docker compose up -d --force-recreate
```

For environment variable changes only:

```bash
docker compose down
docker compose up -d --force-recreate
```
