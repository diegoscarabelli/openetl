"""
LinkedIn connection data pipeline DAG configuration.

Orchestrates the processing and storage of LinkedIn connection CSV exports.
"""

import pendulum

from dags.lib.dag_utils import create_dag
from dags.lib.etl_config import ETLConfig
from dags.pipelines.linkedin.constants import LINKEDIN_FILE_TYPES
from dags.pipelines.linkedin.process import LinkedInProcessor


# Configure the LinkedIn data pipeline.
config = ETLConfig(
    dag_id="linkedin",
    pipeline_print_name="LinkedIn Connections",
    description="Process and store LinkedIn connection data from CSV exports",
    file_types=LINKEDIN_FILE_TYPES,
    max_process_tasks=1,  # Single file processing
    min_file_sets_in_batch=1,
    dag_start_date=pendulum.datetime(year=2025, month=1, day=1, hour=0, tz="UTC"),
    dag_schedule_interval=None,  # Manual trigger only - no schedule
    processor_class=LinkedInProcessor,
    process_format=r"Connections.*\.csv$",  # Match Connections_*.csv files
)

# Create the DAG using default task sequence (ingest >> batch >> process >> store).
dag = create_dag(config, apply_default_task_sequence=True)
