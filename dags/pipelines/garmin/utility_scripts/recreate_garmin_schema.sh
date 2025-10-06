#!/bin/bash
########################################################################################
# Author: Diego Scarabelli
# Created: 2025
# Last Modified: September 5, 2025
########################################################################################
#
# Utility script to drop and recreate the garmin schema with all tables and permissions
# in the local PostgreSQL `lens` database.
# This script performs a destructive operation by dropping the entire schema.
# All existing data will be permanently lost.
# Used in development and testing environments.
#
# Usage: ./recreate_garmin_schema.sh [password]
# Example: ./recreate_garmin_schema.sh garmin
#
# This script will:
# 1. Drop the existing garmin schema (if it exists)
# 2. Create the garmin schema
# 3. Execute tables.ddl to create all tables
# 4. Execute iam.sql with the provided password to set up permissions
#
########################################################################################

set -e  # Exit on any error

# Check if password parameter is provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 <airflow_garmin_password>"
    echo "Example: $0 garmin"
    exit 1
fi

PASSWORD="$1"

# Database connection parameters
DB_HOST="localhost"
DB_PORT="5432" 
DB_USER="postgres"
DB_NAME="lens"

# Get script directory and define paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GARMIN_DIR="$(dirname "$SCRIPT_DIR")"
DAGS_DIR="$(dirname "$(dirname "$GARMIN_DIR")")"

TABLES_DDL="$GARMIN_DIR/tables.ddl"
IAM_SQL="$DAGS_DIR/iam.sql"

# Verify required files exist
if [ ! -f "$TABLES_DDL" ]; then
    echo "Error: tables.ddl not found at $TABLES_DDL"
    exit 1
fi

if [ ! -f "$IAM_SQL" ]; then
    echo "Error: iam.sql not found at $IAM_SQL"
    exit 1
fi

echo "Starting garmin schema recreation..."
echo "Using files:"
echo "  Tables DDL: $TABLES_DDL"
echo "  IAM SQL: $IAM_SQL"
echo

# Function to execute SQL command
execute_sql() {
    local sql_command="$1"
    echo "Executing: $sql_command"
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "$sql_command"
}

# Function to execute SQL file
execute_sql_file() {
    local file_path="$1"
    local description="$2"
    echo "Executing $description: $(basename "$file_path")"
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f "$file_path"
}

echo "1. Dropping existing garmin schema..."
execute_sql "DROP SCHEMA IF EXISTS garmin CASCADE;"

echo
echo "2. Creating garmin schema..."
execute_sql "CREATE SCHEMA garmin;"

echo
echo "3. Creating garmin tables..."
execute_sql_file "$TABLES_DDL" "tables DDL"

echo
echo "4. Applying IAM permissions with password..."
# Create temporary IAM file with the actual password
TEMP_IAM_FILE="/tmp/temp_iam_$$.sql"
sed "s/<REDACTED>/$PASSWORD/g" "$IAM_SQL" > "$TEMP_IAM_FILE"

# Execute the temporary file
execute_sql_file "$TEMP_IAM_FILE" "IAM permissions"

# Clean up temporary file
rm -f "$TEMP_IAM_FILE"

echo
echo "✅ Successfully recreated garmin schema!"
echo "You can now move files from quarantine to process directory and re-run the Garmin DAG."