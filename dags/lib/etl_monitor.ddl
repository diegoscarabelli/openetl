/*
========================================================================================
ETL MONITORING UTILITY TABLES
========================================================================================
Description: Utility tables for ETL monitoring (included in the
             infra_monitor schema of the lens database).
             See also: schemas.ddl for schema definitions.
========================================================================================
*/

CREATE TABLE infra_monitor.airflow_etl_result
(
    dag_id TEXT NOT NULL
    , dag_run_id TEXT NOT NULL
    , dag_start_date TIMESTAMPTZ NOT NULL
    , file_name TEXT NOT NULL
    , success BOOLEAN NOT NULL
    , error_type TEXT
    , traceback TEXT
    , create_ts TIMESTAMPTZ DEFAULT NOW()
    , update_ts TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX airflow_etl_result_uniq
ON infra_monitor.airflow_etl_result (
    dag_id
    , dag_run_id
    , dag_start_date
    , file_name
);

CREATE INDEX airflow_etl_result_dag_id_idx
ON infra_monitor.airflow_etl_result (dag_id);
CREATE INDEX airflow_etl_result_dag_run_id_idx
ON infra_monitor.airflow_etl_result (dag_run_id);
CREATE INDEX airflow_etl_result_dag_start_date_idx
ON infra_monitor.airflow_etl_result (dag_start_date);
CREATE INDEX airflow_etl_result_file_name_idx
ON infra_monitor.airflow_etl_result (file_name);
CREATE INDEX airflow_etl_result_success_idx
ON infra_monitor.airflow_etl_result (success);

COMMENT ON TABLE infra_monitor.airflow_etl_result IS
'Stores the results of ETL operations performed on individual files by Airflow DAGs. '
'Each record represents the outcome of a file processed during an ETL pipeline run, '
'including success status and error details.';
COMMENT ON COLUMN infra_monitor.airflow_etl_result.dag_id IS
'Unique identifier of the Airflow DAG that executed the ETL task.';
COMMENT ON COLUMN infra_monitor.airflow_etl_result.dag_run_id IS
'Unique identifier for the specific DAG run instance.';
COMMENT ON COLUMN infra_monitor.airflow_etl_result.dag_start_date IS
'Timestamp indicating when the DAG run started.';
COMMENT ON COLUMN infra_monitor.airflow_etl_result.file_name IS
'Name of the file processed by the ETL task.';
COMMENT ON COLUMN infra_monitor.airflow_etl_result.success IS
'True if the ETL operation completed successfully for the file; otherwise False.';
COMMENT ON COLUMN infra_monitor.airflow_etl_result.error_type IS
'Short code or description indicating the type of error encountered during ETL processing.';
COMMENT ON COLUMN infra_monitor.airflow_etl_result.traceback IS
'Detailed traceback or error message if the ETL task failed.';
COMMENT ON COLUMN infra_monitor.airflow_etl_result.create_ts IS
'Timestamp when the record was created.';
COMMENT ON COLUMN infra_monitor.airflow_etl_result.update_ts IS
'Timestamp when the record was last updated.';
