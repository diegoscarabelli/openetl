Contents:
- [Introduction](#introduction)
- [Getting Started](#getting-started)
  - [Database Installation and Initialization](#database-installation-and-initialization)
    - [Database Initialization](#database-initialization)
    - [Database Credentials](#database-credentials)
  - [Airflow Installation and Initialization](#airflow-installation-and-initialization)
    - [File Storage Directory](#file-storage-directory)
    - [Updating Airflow Deployments](#updating-airflow-deployments)
  - [Development Environment Setup](#development-environment-setup)
    - [Install Development Dependencies](#install-development-dependencies)
    - [Install Pre-commit Hooks](#install-pre-commit-hooks)
    - [Configure Test Environment](#configure-test-environment)
    - [Verify Your Setup](#verify-your-setup)
- [Repository Structure](#repository-structure)
  - [dags/lib/](#dagslib)
  - [dags/pipelines/](#dagspipelines)
  - [dags/database.ddl](#dagsdatabaseddl)
  - [dags/schemas.ddl](#dagsschemasddl)
  - [dags/iam.sql](#dagsiamsql)
  - [tests/](#tests)
  - [iac/](#iac)
  - [CLAUDE.md](#claudemd)
- [Standard DAG](#standard-dag)
  - [Example Standard DAG](#example-standard-dag)
- [Contributing](#contributing)

# Introduction

OpenETL is an open-source repository that provides a robust framework for building [ETL](https://en.wikipedia.org/wiki/Extract,_transform,_load) data pipelines using leading open-source tools: [Apache Airflow](https://airflow.apache.org/) for orchestration and [PostgreSQL](https://www.postgresql.org/) or its advanced extension [TimescaleDB](https://docs.tigerdata.com/self-hosted/latest/install/) for analytics and time-series data. Break your data free from SaaS silos and return the keys to insights where they belong: with you.

These pipelines are designed to automate the extraction, transformation, validation, analysis and storage of data, ensuring that highly curated datasets are readily available for analysis, reporting and machine learning applications.

By leveraging Airflow's robust scheduling and orchestration capabilities, these pipelines facilitate achieving the following key objectives:

- **Data Extraction**: Automating the retrieval of data from diverse sources, such as APIs, databases, and file systems.
- **Data Transformation**: Applying business logic and data wrangling to prepare raw data for analysis or storage.
- **Data Validation**: Ensuring data quality and integrity through automated checks and validations.
- **Data Storage**: Persisting processed data into databases and file systems for downstream consumption.

The repository's modular structure and reusable components make it easy to extend and customize pipelines to meet specific requirements. Whether you're building a simple ETL pipeline or a complex data processing workflow, this repository provides the tools and patterns to streamline development and deployment.

# Getting Started

This framework requires [PostgreSQL](https://www.postgresql.org/) as the analytics database and [Apache Airflow](https://airflow.apache.org/) to orchestrate ETL pipelines. All components run locally or on-premises, no cloud services are required.

To simplify deployment, the [iac](iac/) (Infrastructure as Code) directory provides installation scripts and configuration templates for setting up PostgreSQL, TimescaleDB, and Airflow. These resources support both development and production environments.

## Database Installation and Initialization

You can download PostgreSQL from the official [website](https://www.postgresql.org/download/) or install it using a package manager such as `apt` (Linux) or `brew` (macOS). For most use cases, we recommend installing [TimescaleDB](https://docs.tigerdata.com/self-hosted/latest/install/), which extends PostgreSQL with advanced time-series capabilities.

Installation and configuration templates are provided in the [iac/timescaledb/README.md](iac/timescaledb/README.md) directory. These resources are meant for a Linux server and serve as a foundation. You may need to adapt them for your specific operating system and deployment needs.

### Database Initialization

**Prerequisites:**
- Ensure PostgreSQL is installed and running.
- To enable TimescaleDB features, install the TimescaleDB extension.
- To enable vector search features, install the pgvectorscale extension.

After installing and starting PostgreSQL, proceed to create and initialize the analytics database (**lens**). Optionally, you can enable extensions such as TimescaleDB for time-series capabilities. Next, define the required schemas and configure users and permissions to ensure secure and organized access.

> **Note:** If TimescaleDB or pgvectorscale are not required, comment out their respective `CREATE EXTENSION` statements in `dags/schemas.ddl` before initializing the database.

> **IMPORTANT:** Before executing `dags/iam.sql`, replace all `<REDACTED>` password placeholders with the actual passwords for each database user.

To initialize the **lens** database, execute the following steps:
```bash
# Step 1: Create the analytics database (lens).
psql -U postgres -d postgres -f dags/database.ddl

# Step 2: Initialize schemas and extensions.
# (Comment out extension sections in dags/schemas.ddl if TimescaleDB or pgvectorscale are not needed.)
psql -U postgres -d lens -f dags/schemas.ddl

# Step 3: Update passwords in dags/iam.sql.
# (Replace all <REDACTED> placeholders with actual passwords.)

# Step 4: Create users, roles, and permissions.
psql -U postgres -d lens -f dags/iam.sql

# Step 5: Create ETL monitoring tables.
psql -U postgres -d lens -f dags/lib/etl_monitor.ddl

# Step 6: Create pipeline-specific tables (example: Garmin pipeline).
psql -U postgres -d lens -f dags/pipelines/garmin/tables.ddl
psql -U postgres -d lens -f dags/pipelines/garmin/tables_tsdb.ddl
```

> **Tip:** If your PostgreSQL `pg_hba.conf` is set to require password authentication, connect using `psql -h localhost` to ensure password prompts are triggered.

### Database Credentials
To allow Airflow tasks to connect securely to the database, store credentials as individual JSON files within the directory specified by the `SQL_CREDENTIALS_DIR` environment variable. Each file must be named after the corresponding database user (`<username>.json`) and follow this structure:

```json
{
   "user": "<username>",
   "password": "<password>"
}
```

**Examples:**
- `postgres.json` — Credentials for the PostgreSQL superuser.
- `airflow_garmin.json` — Credentials for the pipeline user `airflow_garmin` (named as `airflow_<dag_id>`).

These credential files are loaded by the framework at runtime to authenticate database connections for Airflow tasks.

## Airflow Installation and Initialization

Apache Airflow supports multiple deployment methods, providing flexibility for various environments and requirements. The data pipeline code in this repository is deployment-agnostic, ensuring compatibility regardless of the chosen setup.

This repository provides comprehensive templates and step-by-step instructions for two recommended deployment approaches, streamlining the setup of core infrastructure components. Detailed resources for both methods are available in the [Infrastructure as Code](#iac) section.

1. **[Astro CLI](https://www.astronomer.io/docs/astro/cli/install-cli)** (Astronomer distribution): Recommended for local development on macOS or Windows. Install PostgreSQL/TimescaleDB locally for the analytics database (`lens`), then use Astro CLI and Docker Desktop to run Airflow. Astro CLI includes a containerized PostgreSQL instance for Airflow's metadata database, configured to use port 5433 to avoid conflicts with the analytics database on port 5432. A comprehensive setup guide is provided in [iac/astro_cli_docker/README.md](iac/astro_cli_docker/README.md), covering initialization, configuration, and deployment.

   > **Note:** Before starting Astro, export `.env` variables to your shell with `export $(cat .env | grep -v "^#" | grep -v "^$" | xargs)`. This is required before each `astro dev start` to enable Docker Compose variable substitution in volume mounts.

2. **[Docker Compose](https://airflow.apache.org/docs/apache-airflow/stable/installation/index.html#using-production-docker-images)**: Recommended for production or non-development deployments on Ubuntu/Linux servers. Install PostgreSQL/TimescaleDB to host both the analytics database (`lens`) and Airflow's metadata database (`airflow_db`) on the same PostgreSQL instance. Deploy Airflow using Docker Compose, which connects to the colocated databases via the Docker bridge network. A comprehensive installation guide is provided in [iac/airflow/README.md](iac/airflow/README.md), covering environment setup, database initialization, and deployment automation.

   > **Note:** Both deployment methods require an `.env` file to configure essential environment variables for Airflow and pipeline execution. Be aware of key differences.

### File Storage Directory

The local file storage directory for data pipelines is configured using the `DATA_DIR` environment variable. If `DATA_DIR` is not set, it defaults to `./data` at the same level as the Docker Compose root. For Astronomer CLI deployments, the default is `{project_root}/data/`; for Docker Compose, it is `~/airflow/data/`. Before starting Airflow with Astronomer, manually create this directory to ensure correct file permissions, as Airflow will access it using the user that launches the containers.

The host-side `DATA_DIR` path is mounted to a fixed container path:
- Astronomer: Maps to `/usr/local/airflow/data` inside container.
- Docker Compose: Maps to `/opt/airflow/data` inside container.
- Python code reads `DATA_DIR` environment variable (set by docker-compose) to locate data.

The directory structure is as follows:

```
/data/{dag_id}/
├── ingest/       # Raw incoming files
├── process/      # Files being processed
├── store/        # Successfully processed files
└── quarantine/   # Failed/invalid files
```

Each DAG has its own subdirectory (named after the DAG ID as defined in [`dags.lib.etl_config.ETLConfig.__post_init__`](dags/lib/etl_config.py)), which contains a subdirectory for each data state, as defined in the [`dags.lib.filesystem_utils.DataState`](dags/lib/filesystem_utils.py) class. The data states are:
- `ingest`: This is the mail box directory where files arrive for processing. It should be emptied by the next DAG run.
- `process`: Contains files that need to be processed by the DAG. Unless a DAG run is underway, this directory should be empty.
- `quarantine`: Contains files that have been quarantined due to errors or issues during processing.
- `store`: Contains files that have been successfully processed and stored for long-term use.

### Updating Airflow Deployments

Both Astro CLI and Docker Compose deployments require different procedures depending on the type of change being applied.

For Astro CLI deployments on macOS/Windows, see the [Updating Deployments](iac/astro_cli_docker/README.md#updating-deployments) section in the Astro CLI documentation for detailed procedures on when to restart versus rebuild.

For Docker Compose deployments on Ubuntu/Linux, see the [Deployment Updates](iac/airflow/README.md#deployment-updates) section in the Airflow infrastructure documentation for detailed procedures on when to rebuild images versus when to use `--force-recreate` for configuration-only changes.

## Development Environment Setup

If you plan to contribute to OpenETL or run tests locally, follow these additional setup steps after completing the database and Airflow installation above.

### Install Development Dependencies

Install the Python packages required for development, testing, and code formatting:

```bash
pip install -r requirements_dev.txt
```

This installs pytest, coverage tools, pre-commit, and all formatting tools (Black, Autoflake, Docformatter, SQLFluff).

### Install Pre-commit Hooks

Set up pre-commit hooks to automatically format code before each commit:

```bash
pre-commit install
```

The hooks are configured in `.pre-commit-config.yaml` and will run formatters automatically, preventing improperly formatted code from being committed.

### Configure Test Environment

Tests require a PostgreSQL database running on `localhost:5432`.

**Default Configuration (No setup required)**

By default, tests connect to:
- Host: `localhost:5432`
- Database: `postgres`
- User: `postgres`
- Password: `postgres`

If you have PostgreSQL installed with these default credentials, tests will work immediately with no configuration.

**Override Password (Using credentials file)**

If your `postgres` user has a different password, create a credentials file `$SQL_CREDENTIALS_DIR/postgres.json`:

   ```json
   {
     "user": "postgres",
     "password": "your_actual_password"
   }
   ```

The test configuration ([`tests/dags/lib/conftest.py`](tests/dags/lib/conftest.py)) reads the `SQL_CREDENTIALS_DIR` environment variable from your `.env` file, looks for `postgres.json` in that directory, and uses the password to construct the database connection URL. If the file doesn't exist, it falls back to the default password `postgres`.

**Override Database URL (Complete customization)**

To use a completely different database (different host, port, database name, or user), add to your `.env` file:

```
TEST_DB_URL=postgresql+psycopg2://user:password@host:port/database
```

### Verify Your Setup

Run the test suite to ensure everything is configured correctly:

```bash
make test
```

If all tests pass, your development environment is ready! See [Contributing](#contributing) for detailed contribution guidelines.

# Repository Structure

## [dags/lib/](dags/lib)

Contains Python modules that provide utility functions to streamline the development of scripts in the [dags/pipelines](dags/pipelines) directory. These include utilities for working with databases such as [Postgresql](https://www.postgresql.org/), the filesystem hosting the data to process, Airflow DAG configuration and construction, ETL results tracking, and general-purpose data manipulation utilities.

The library includes the following key modules:

- **[`dag_utils.py`](dags/lib/dag_utils.py)**: Core utilities for Airflow DAG creation and ETL processing, including standard task functions (`ingest`, `batch`, `process_wrapper`, `store`), the abstract `Processor` base class for custom data processing logic, and the `create_dag()` function for assembling complete DAGs from configuration.

- **[`etl_config.py`](dags/lib/etl_config.py)**: Configuration management through the `ETLConfig` dataclass, providing unified configuration for DAG parameters, file processing settings, database connections, task-specific configurations, and directory management with validation and sensible defaults.

- **[`sql_utils.py`](dags/lib/sql_utils.py)**: Database utilities for working with SQLAlchemy ORM models and PostgreSQL databases, including engine and session creation, custom ORM base classes with timestamp columns, bulk upsert operations, credential management for Airflow SQL users, and query type enumeration. 

- **[`filesystem_utils.py`](dags/lib/filesystem_utils.py)**: Filesystem management utilities including the `DataState` enum for pipeline data states (ingest, process, store, quarantine), `ETLDataDirectories` for standardized directory management, and `FileSet` classes for coordinating file processing across different file types.

- **[`etl_monitor_utils.py`](dags/lib/etl_monitor_utils.py)**: ETL result tracking and database logging utilities featuring SQLAlchemy ORM models for ETL results tables, result record dataclasses, and the `ETLResult` class for comprehensive result management and database I/O operations.

- **[`etl_monitor.ddl`](dags/lib/etl_monitor.ddl)**: SQL Data Definition Language file containing utility table definitions for ETL monitoring (specifically the `airflow_etl_result` table in the `infra_monitor` schema) used to track file processing execution results.

- **[`logging_utils.py`](dags/lib/logging_utils.py)**: Airflow-aware logging utilities for data pipeline tasks, providing the `AirflowAwareLogger` class that automatically uses Airflow's native task logger when running in an Airflow context and falls back to standard Python logging otherwise, ensuring clean, properly formatted logs in Airflow.

## [dags/pipelines/](dags/pipelines)

Contains a subdirectory for each DAG. Each subdirectory includes the DAG definition file and Python scripts executed by tasks within the DAG using the Airflow `PythonOperator`. Additionally, each subdirectory contains Data Definition Language (DDL) files that define database objects such as tables and views associated with the pipeline. These include:

- `tables.ddl`: Standard SQL definitions for tables and views.
- `tables_tsdb.ddl`: [TimescaleDB](https://github.com/timescale/timescaledb)-specific definitions, including hypertables and continuous aggregates.

Each subdirectory also contains a `README.md` file that offers comprehensive details about the pipeline. This includes contextual background, prerequisites, configuration instructions, data ingestion and storage workflows, as well as data consumption patterns.

## [dags/database.ddl](dags/database.ddl)

Creates the `lens` database, which serves as the central analytics database for all data pipeline outputs. This script must be executed first, before any schema or table initialization. The database is created with UTF-8 encoding to ensure proper handling of international characters and diverse data sources.

## [dags/schemas.ddl](dags/schemas.ddl)

Defines the database schema initialization for the `lens` database, a [TimescaleDB](https://docs.timescale.com/) instance built on PostgreSQL. This database serves as the central data warehouse for all pipeline outputs and analytical datasets. The schemas organize data into logical domains, and optional extensions (TimescaleDB, pgvectorscale) can be enabled for time-series and vector search capabilities. For development and staging, a local database instance is available at `localhost` and configured identically to production, using the same schemas, SQL users, and IAM configurations to ensure consistency across environments.

## [dags/iam.sql](dags/iam.sql)

Defines the Identity and Access Management (IAM) configuration for SQL users and roles adopted by Airflow data pipelines, establishing a secure, role-based access control system. This security model ensures that each pipeline operates with minimal necessary privileges while maintaining data integrity and preventing unauthorized access across different data domains. The same IAM structure is replicated in both production and local development environments to maintain security consistency.

The IAM configuration includes:

- **Pipeline-specific users**: Each DAG has its own dedicated SQL user (following the pattern `airflow_<dag_id>`) with precisely scoped permissions for data ingestion and processing.
- **Schema-level permissions**: Granular access controls that align with the logical data organization defined in [`dags/schemas.ddl`](dags/schemas.ddl).
- **Credential management**: Database credentials are stored as JSON files in a directory specified by the `SQL_CREDENTIALS_DIR` environment variable and accessed by pipelines through the utilities provided in the [`dags/lib/sql_utils.py`](dags/lib/sql_utils.py) module. See [Database Credentials](#database-credentials) for details on credential file format.
- **Read-only access**: Additional read-only users can be defined for analytical queries and reporting tools like [Apache Superset](https://github.com/diegoscarabelli/iac/tree/main/superset).

## [tests/](tests/)

[Pytest](https://docs.pytest.org/en/stable/) is used to execute unit tests. Many of these tests leverage `conftest.py` files to provide reusable fixtures.

To run the tests, execute the following command:

```bash
make test
```

This command sets up your local environment, runs the tests, and displays coverage information. The Python environment and test configurations are defined in the [`Makefile`](Makefile), ensuring consistency and simplifying the setup process.

Alternatively, you can use the test runner in your preferred IDE or editor. This approach allows you to set breakpoints and step through the tests for debugging purposes.

## [iac/](iac/)

The Infrastructure as Code (IaC) directory contains deployment configuration, installation scripts, and templates for the core infrastructure components required to run the data pipelines.

- **[airflow/](iac/airflow/)**: Docker Compose deployment configuration for Apache Airflow on Ubuntu/Linux production servers. Includes installation scripts (`docker_install.sh`, `airflow_install.sh`), environment configuration (`.env`), Docker Compose files, and database initialization scripts (`airflow_db.ddl`, `airflow_db_grants.ddl`). See [iac/airflow/README.md](iac/airflow/README.md) for detailed installation instructions.

- **[astro_cli_docker/](iac/astro_cli_docker/)**: Astro CLI deployment configuration for local development on macOS/Windows. Includes setup guide, configuration templates (`.env.template`, `config.yaml.template`), and deployment instructions. See [iac/astro_cli_docker/README.md](iac/astro_cli_docker/README.md) for comprehensive setup and troubleshooting documentation.

- **[timescaledb/](iac/timescaledb/)**: PostgreSQL and TimescaleDB installation and configuration for Ubuntu/Linux servers. Includes installation scripts, configuration files (`postgresql.conf`, `pg_hba.conf`), and database setup scripts. See [iac/timescaledb/README.md](iac/timescaledb/README.md) for comprehensive installation and maintenance documentation.

## [CLAUDE.md](CLAUDE.md)

Project-specific instructions for Claude Code (claude.ai/code) when working with this repository. This file provides essential context about the project structure, coding standards, and development workflows to ensure consistent and accurate AI-assisted development. Key sections include:

- **README.md reference**: Emphasizes that the main README is the source of truth for project understanding.
- **Code execution environment**: Documents the conda environment setup and activation commands.
- **Mandatory formatting protocol**: Detailed step-by-step instructions for code quality checks, combining manual review with automated tools (Black, Autoflake, Docformatter, SQLFluff).
- **Quality checklist**: Comprehensive checklist covering spacing, line length, docstring format, type hints, and import organization that must be verified before completing any code task.

# Standard DAG

This repository offers utilities for the configuration and assembly of Airflow DAGs and their associated tasks. A standard design pattern that can be easily customized is facilitated by the following components:

- **[`ETLConfig`](dags/lib/etl_config.py)**: A comprehensive data class that provides unified configuration for data pipelines, including DAG parameters, file processing settings, database connections, and task-specific configurations.
- **[`dags/lib/dag_utils.py`](dags/lib/dag_utils.py)**: A module containing functions and classes for standard ETL tasks that form a four-step sequential pipeline:
  1. **`task_ingest`**: Moves files from the `ingest` directory to `process`/`store` directories based on regex patterns defined in the configuration.
  2. **`task_batch`**: Groups files by timestamp into file sets and creates processing batches respecting concurrency limits.
  3. **`task_process`**: Dynamically expands into multiple parallel tasks, each processing a batch of file sets using a custom `Processor` subclass.
  4. **`task_store`**: Moves successfully processed files to storage and failed files to quarantine based on ETL results.

The [`create_dag()`](dags/lib/dag_utils.py) function assembles these components into a complete DAG using the standard pattern, while allowing customization through configuration parameters and custom callable implementations.

## Example Standard DAG

The following example demonstrates how to create a standard DAG using the actual API:

```python
import re

from enum import Enum

from dags.lib.dag_utils import create_dag, Processor
from dags.lib.etl_config import ETLConfig


# Define file types for your pipeline
class MyFileTypes(Enum):
    DATA = re.compile(r".*\.csv$")
    METADATA = re.compile(r".*\.json$")

# Create a custom processor
class MyProcessor(Processor):
    def process_file_set(self, file_set, session):
        # Implement your custom processing logic here
        pass

# Configure the pipeline
config = ETLConfig(
    dag_id="my_pipeline",
    pipeline_print_name="My Data Pipeline",
    description="Example DAG showing the standard pattern",
    processor_class=MyProcessor,
    file_types=MyFileTypes,
    max_process_tasks=3,
    min_file_sets_in_batch=2,
)

# Create the DAG
dag = create_dag(config)
```

This produces a DAG with four ordered tasks:
```python
task_ingest >> task_batch >> task_process >> task_store
```

The `create_dag()` function returns the DAG object, allowing you to customize it further by adding additional tasks, modifying the task order, or overriding default behaviors through the configuration parameters.

# Contributing

We welcome contributions from the community! Whether you're fixing bugs, adding features, improving documentation, or suggesting enhancements, your contributions help make OpenETL better for everyone.

## How to Contribute

For detailed information on contributing to this project, please see our [CONTRIBUTING.md](CONTRIBUTING.md) guide, which includes:

- **External Contributors Workflow**: Step-by-step fork-based workflow for contributing
- **Reporting Bugs and Suggesting Features**: Templates and guidelines for issues
- **Code Standards**: Formatting rules, testing requirements, and documentation guidelines
- **Pull Request Process**: Pre-submission checklist and code review expectations

## Quick Start for Contributors

1. Complete the [Getting Started](#getting-started) setup (Database, Airflow, and Development Environment)
2. Fork the repository on GitHub and clone your fork
3. Create a feature branch: `git checkout -b feature/your-feature`
4. Make your changes following our [code standards](CONTRIBUTING.md#formatting)
5. Run tests: `make test`
6. Format code: `make format && make check-format`
7. Commit and push your changes to your fork
8. Open a Pull Request

For detailed contribution guidelines, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Code of Conduct

This project adheres to a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Questions?

- Check the [documentation](README.md)
- Open a [Discussion](https://github.com/diegoscarabelli/openetl/discussions)
- Submit an [Issue](https://github.com/diegoscarabelli/openetl/issues)
