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
from dags.pipelines.wid.process import WidProcessor

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

# Prepend the extract task that downloads and unpacks the WID bulk ZIP.
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

# Define the task sequence: extract >> ingest >> batch >> process >> store.
task_extract >> task_ingest >> task_batch >> task_process >> task_store
