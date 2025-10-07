"""
Garmin Connect data pipeline DAG configuration.

Orchestrates the extraction, processing, and storage of Garmin Connect wellness and
activity data.
"""

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.python import PythonOperator

from dags.lib.dag_utils import create_dag
from dags.lib.etl_config import ETLConfig
from dags.pipelines.garmin.constants import GARMIN_FILE_TYPES
from dags.pipelines.garmin.extract import extract
from dags.pipelines.garmin.process import GarminProcessor


# Configure the Garmin Connect data pipeline.
config = ETLConfig(
    dag_id="garmin",
    pipeline_print_name="Garmin",
    description="Extract, process, and store Garmin Connect data",
    file_types=GARMIN_FILE_TYPES,
    max_process_tasks=8,
    min_file_sets_in_batch=1,
    dag_start_date=pendulum.datetime(
        year=2008, month=1, day=1, hour=1, tz="America/Los_Angeles"
    ),
    dag_schedule_interval=timedelta(days=1),
    dag_dagrun_timeout=timedelta(hours=12),
    processor_class=GarminProcessor,
)

# Create the DAG using create_dag without default task sequence.
dag = create_dag(config, apply_default_task_sequence=False)

# Get the existing tasks from the DAG.
task_ingest = dag.get_task("ingest")
task_batch = dag.get_task("batch")
task_process = dag.get_task("process")
task_store = dag.get_task("store")

# Add extract task before the default sequence.
with dag:
    task_extract = PythonOperator(
        task_id="extract",
        python_callable=extract,
        op_kwargs={
            "ingest_dir": config.data_dirs.ingest,
            "data_interval_start": (
                "{{ dag_run.conf.get('data_interval_start') or "
                "prev_data_interval_end_success or "
                "(data_interval_end - macros.timedelta(days=1)) }}"
            ),
            "data_interval_end": (
                "{{ dag_run.conf.get('data_interval_end') or data_interval_end }}"
            ),
        },
        doc_md=(
            "Download data from Garmin Connect for the specified date range. Files are "
            "saved with standardized naming conventions to the "
            "{config.data_dirs.ingest} directory for downstream processing."
        ),
    )

# Define the new task sequence: extract >> ingest >> batch >> store.
task_extract >> task_ingest >> task_batch >> task_process >> task_store
