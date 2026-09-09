"""
WID data pipeline DAG configuration.

Orchestrates the download, processing, and storage of the World Inequality Database bulk
dataset. A custom extract task downloads and unpacks the WID ZIP before the standard
ingest -> batch -> process -> store sequence. Manual trigger only (WID releases roughly
once a year); each run fully replaces the dataset per country.

Note: This file must contain 'airflow' for Airflow's safe mode DAG discovery.
"""

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.python import PythonOperator

from dags.lib.dag_utils import create_dag
from dags.lib.etl_config import ETLConfig
from dags.pipelines.wid.constants import WID_FILE_TYPES
from dags.pipelines.wid.extract import extract
from dags.pipelines.wid.process import (
    finalize_observation_table,
    prepare_observation_table,
    WidProcessor,
)

# Configure the WID data pipeline.
config = ETLConfig(
    dag_id="wid",
    pipeline_print_name="WID",
    description="Download, process, and store the World Inequality Database.",
    file_types=WID_FILE_TYPES,
    processor_class=WidProcessor,
    max_process_tasks=8,
    min_file_sets_in_batch=1,
    dag_start_date=pendulum.datetime(year=2025, month=1, day=1, hour=0, tz="UTC"),
    dag_schedule_interval=None,  # Manual trigger only.
    dag_dagrun_timeout=timedelta(hours=12),
)

# Build the DAG without the default sequence so the custom extract task can lead.
dag = create_dag(config, apply_default_task_sequence=False)

# Fetch the standard tasks created by create_dag.
task_ingest = dag.get_task("ingest")
task_batch = dag.get_task("batch")
task_process = dag.get_task("process")
task_store = dag.get_task("store")

# Add the custom tasks that bracket the load: extract downloads and unpacks the bulk
# ZIP; prepare drops the observation constraints and truncates it for a full reload;
# finalize rebuilds the constraints (which also validates the load).
with dag:
    task_extract = PythonOperator(
        task_id="extract",
        python_callable=extract,
        execution_timeout=timedelta(hours=2),
        op_kwargs={"ingest_dir": config.data_dirs.ingest},
        doc_md=(
            "Download the WID bulk ZIP and extract the per-country observation and "
            "metadata CSVs (plus the countries CSV) into the ingest directory."
        ),
    )
    task_prepare = PythonOperator(
        task_id="prepare",
        python_callable=prepare_observation_table,
        op_kwargs={"sql_user": config.postgres_user},
        doc_md=(
            "Drop the observation primary key and foreign keys and truncate the table "
            "so the process tasks can bulk-load into it unindexed."
        ),
    )
    task_finalize = PythonOperator(
        task_id="finalize",
        python_callable=finalize_observation_table,
        execution_timeout=timedelta(hours=1),
        op_kwargs={"sql_user": config.postgres_user},
        doc_md=(
            "Rebuild the observation primary key and foreign keys after the load; the "
            "rebuild also validates it (duplicate keys or orphaned codes fail here)."
        ),
    )

# Define the task sequence:
# extract >> ingest >> batch >> prepare >> process >> finalize >> store.
(
    task_extract
    >> task_ingest
    >> task_batch
    >> task_prepare
    >> task_process
    >> task_finalize
    >> task_store
)
