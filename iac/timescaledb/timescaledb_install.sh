#!/usr/bin/bash

# ======================================================================================
# TIMESCALEDB INSTALLATION SCRIPT
# ======================================================================================
# Description: This script installs PostgreSQL 17, TimescaleDB, and pgvectorscale
#              extensions on Ubuntu/Linux. It configures the database server with
#              custom settings and prepares it for analytics workloads.
#
# Prerequisites:
#   - Ubuntu/Linux server with sudo privileges.
#   - Internet connection for downloading packages.
#
# Configuration:
#   - Before running, review and customize configuration files:
#     * iac/timescaledb/postgresql.conf - PostgreSQL server configuration
#     * iac/timescaledb/pg_hba.conf - Client authentication configuration
#
# Post-Installation:
#   - Set the postgres user password manually (see MANUAL_STEPS section at end).
#   - Run database initialization scripts from dags/:
#     * dags/database.ddl - Create lens database
#     * dags/schemas.ddl - Initialize schemas and extensions
#     * dags/iam.sql - Create users and permissions
#
# Usage:
#   bash timescaledb_install.sh
# ======================================================================================

# Get the directory where this script is located.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create installation log file.
touch timescaledb_installation.log
echo -e "TimescaleDB Installation Log\n" >> timescaledb_installation.log
date >> timescaledb_installation.log

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
exec 1>timescaledb_installation.log 2>&1

# Add the PostgreSQL apt repository.
echo -e "--> Add the PostgreSQL apt repository\n" >> timescaledb_installation.log
sudo apt -y update
sudo apt -y install gnupg postgresql-common apt-transport-https lsb-release wget

# Run the repository setup script.
echo -e "--> Run the repository setup script\n" >> timescaledb_installation.log
sudo bash /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -p

# Add the TimescaleDB third party repo and install the TimescaleDB GPG key.
echo -e "--> Add the TimescaleDB third party repo and install TimescaleDB GPG key\n" >> timescaledb_installation.log
echo "deb https://packagecloud.io/timescale/timescaledb/ubuntu/ $(lsb_release -c -s) main" | sudo tee /etc/apt/sources.list.d/timescaledb.list
wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg

# Update local repository.
echo -e "--> Update local repository\n" >> timescaledb_installation.log
sudo apt -y update

# Install TimescaleDB.
echo -e "--> Install TimescaleDB\n" >> timescaledb_installation.log
sudo apt -y install timescaledb-2-postgresql-17

# Restart PostgreSQL and create the TimescaleDB extension.
echo -e "--> Restart PostgreSQL and create the TimescaleDB extension\n" >> timescaledb_installation.log
sudo systemctl restart postgresql

# Copy the latest version of pg_hba.conf and postgresql.conf to /etc/postgresql/17/main/.
echo -e "--> Copy the latest version of pg_hba.conf and postgresql.conf to /etc/postgresql/17/main/\n" >> timescaledb_installation.log
sudo cp "$SCRIPT_DIR/pg_hba.conf" /etc/postgresql/17/main/pg_hba.conf
sudo cp "$SCRIPT_DIR/postgresql.conf" /etc/postgresql/17/main/postgresql.conf
sudo chown postgres:postgres /etc/postgresql/17/main/postgresql.conf
sudo chown postgres:postgres /etc/postgresql/17/main/pg_hba.conf

# Restart the Postgres service.
echo -e "--> Restart the Postgres service\n" >> timescaledb_installation.log
sudo systemctl restart postgresql

# Install pgvectorscale extension.
echo -e "--> Install pgvectorscale extension\n" >> timescaledb_installation.log

# Install Rust.
echo -e "--> Install Rust\n" >> timescaledb_installation.log
sudo snap remove curl
sudo apt install -y curl
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# Source cargo environment for current shell.
source "$HOME/.cargo/env"

# Install build dependencies.
echo -e "--> Install build dependencies\n" >> timescaledb_installation.log
sudo apt update
sudo apt install -y pkg-config openssl libssl-dev clang postgresql-server-dev-17 build-essential jq

# Download and install pgvector.
echo -e "--> Download and install pgvector\n" >> timescaledb_installation.log
cd /tmp
git clone --branch v0.8.0 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install

# Download and install pgvectorscale.
echo -e "--> Download and install pgvectorscale\n" >> timescaledb_installation.log
cd /tmp
git clone --branch 0.7.1 https://github.com/timescale/pgvectorscale
cd pgvectorscale/pgvectorscale

# Install cargo-pgrx with the same version as pgrx.
cargo install --locked cargo-pgrx --version $(cargo metadata --format-version 1 | jq -r '.packages[] | select(.name == "pgrx") | .version')
cargo pgrx init --pg17 pg_config

# Build and install pgvectorscale.
cargo pgrx install --release

echo -e "--> Installation complete\n" >> timescaledb_installation.log

# The following steps are executed manually.
: <<'MANUAL_STEPS'
# Open the psql command-line utility as the postgres superuser and
# set the password for the postgres user.
sudo -u postgres psql
ALTER USER postgres WITH PASSWORD '<enter_password>';

MANUAL_STEPS
