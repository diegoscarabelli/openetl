#!/usr/bin/bash

# ======================================================================================
# AIRFLOW INSTALLATION SCRIPT
# ======================================================================================
# Description: This script installs Apache Airflow using Docker Compose. It creates
#              the necessary directory structure, configures environment variables,
#              and sets up an admin user.
#
# Prerequisites:
#   - Docker Engine must be installed (use docker_install.sh).
#   - PostgreSQL must be running with airflow_db database created.
#   - Run Airflow metadata database setup scripts airflow_db.ddl and
#     airflow_db_grants.ddl
#
# Configuration:
#   - Before running, edit iac/airflow/.env and set:
#     * DAGS_DIR - Path to dags directory
#     * SQL_CREDENTIALS_DIR - Path to SQL credentials directory
#     * Optionally: SQL_DB_HOST, DATA_DIR
#   - Update admin user credentials in this script (lines 79-83):
#     * YourFirstName
#     * YourLastName
#     * your.email@example.com
#     * <REDACTED_PASSWORD>
#
# Usage:
#   bash airflow_install.sh
# ======================================================================================

# Get the directory where this script is located and the repo root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Create installation log file.
touch airflow_installation.log
echo -e "Airflow Installation Log\n" >> airflow_installation.log
date  >> airflow_installation.log

# Capture logging to file.
# Save file descriptors so they can be restored to whatever they were before
# redirection or used themselves to output to whatever they were before the
# following redirect.
exec 3>&1 4>&2
# Restore file descriptors for particular signals. Not generally necessary
# since they should be restored when the sub-shell exits.
trap 'exec 2>&4 1>&3' 0 1 2 3
# Redirect stdout to log file then redirect stderr to stdout.
# Note that the order is important when you want them going to the same file.
# stdout must be redirected before stderr is redirected to stdout.
exec 1>airflow_installation.log 2>&1

# Create the airflow directory.
echo -e "--> Creating the airflow directory\n" >> airflow_installation.log
mkdir ~/airflow
mkdir ~/airflow/logs

# Copy environment configuration and set AIRFLOW_UID/GID.
# AIRFLOW_UID is set to your user ID and AIRFLOW_GID to 0 (root group).
# This ensures that files created by Airflow inside the container have the correct
# permissions on the host.
echo -e "--> Copying environment configuration\n" >> airflow_installation.log
cp "${SCRIPT_DIR}/.env" ~/airflow/.env
echo -e "\nAIRFLOW_UID=$(id -u)\nAIRFLOW_GID=0" >> ~/airflow/.env

# Copy Airflow configuration files.
cp "${SCRIPT_DIR}/docker-compose.yaml" ~/airflow/docker-compose.yaml
cp "${SCRIPT_DIR}/Dockerfile" ~/airflow/Dockerfile
cp "${REPO_ROOT}/requirements.txt" ~/airflow/requirements.txt

# Initialize Airflow database schema.
docker compose up airflow-init --build 

# Start Airflow.
docker compose up --force-recreate -d

# Creates an admin user for web UI access.
# Make sure that a permanent user with Admin role is created. First delete the
# existing user with the same username, then create a new one.
docker compose exec airflow-scheduler airflow users delete --username airflow
docker compose exec airflow-scheduler airflow users create \
    --username airflow \
    --firstname YourFirstName \
    --lastname YourLastName \
    --role Admin \
    --email your.email@example.com \
    --password <REDACTED_PASSWORD>
    