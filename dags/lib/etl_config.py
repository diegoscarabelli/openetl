"""
Configuration management through the ETLConfig dataclass for data pipelines.

This module provides unified configuration for DAG parameters, file processing
settings, database connections, task-specific configurations, and directory
management. It includes:
    - ETLConfig dataclass with validation and sensible defaults.
    - DAG parameter configuration for Airflow integration.
    - File processing and batch configuration settings.
    - Database connection and credential management.
    - Directory structure management for pipeline data states.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Optional, Callable, Type, Dict, Union, Any

import pendulum

from dags.lib.filesystem_utils import ETLDataDirectories, DefaultFileTypes


@dataclass
class ETLConfig:
    """
    Configuration parameters for Airflow DAGs and pipeline tasks.

    For a list of DAG-level parameters, see:
    https://www.astronomer.io/docs/learn/airflow-dag-parameters/
    """

    # ----------------------------------------------------------------------------------
    # DAG object configuration parameters
    # ----------------------------------------------------------------------------------

    # Name of the DAG. This is also used for naming the ETL data directories associated
    # with this DAG.
    dag_id: str

    # Callable functions used in DAG tasks to override the default functions defined
    # in dag_utils.py.  The functions must have the same signature as the default
    # functions.
    ingest_callable: Optional[Callable] = None
    batch_callable: Optional[Callable] = None
    store_callable: Optional[Callable] = None

    # Callable class to be used in the process task. This must be a subclass of the
    # Processor class defined in dags.lib.dag_utils.py.
    processor_class: Optional[Type[Any]] = None

    # Additional keyword arguments to be passed to the callable functions used in tasks.
    extra_ingest_kwargs: Dict[str, Any] = field(default_factory=dict)
    extra_batch_kwargs: Dict[str, Any] = field(default_factory=dict)
    extra_processor_init_kwargs: Dict[str, Any] = field(default_factory=dict)
    extra_store_kwargs: Dict[str, Any] = field(default_factory=dict)

    # File types and the corresponding regex patterns to be used in the FileSet class.
    # For example:
    # class FileTypes(Enum):
    #     DATA = re.compile(r".*data.*\.csv$")
    #     METADATA = re.compile(r".*metadata.*\.json$")
    #     CONFIG = re.compile(r".*config.*\.json$")
    file_types: Type[Enum] = DefaultFileTypes

    # Maximum number of process tasks to run in parallel.
    max_process_tasks: int = 1

    # Minimum number of file sets to process in a single process task.
    min_file_sets_in_batch: int = 1

    # Whether to enable autoflush for SQLAlchemy sessions.
    autoflush: bool = True

    # How long a DAG run should be up before timing out / failing, so that new DAG
    # runs can be created.
    dag_dagrun_timeout: timedelta = timedelta(hours=12)

    # Timestamp that the schedule_interval parameter is relative to. Must be a fixed
    # pendulum.datetime in the past. See:
    # https://airflow.apache.org/docs/apache-airflow/stable/authoring-and-scheduling/timezone.html#time-zone-aware-dags
    dag_start_date: pendulum.datetime = pendulum.datetime(
        year=2025, month=1, day=1, tz="UTC"
    )

    # Time interval between consecutive DAG runs or cron expression, which the DAG
    # will use to automatically schedule runs. If None, the DAG is not scheduled.
    dag_schedule_interval: Optional[Union[timedelta, str]] = None

    # The scheduler, by default, kicks off a DAG Run for any data interval that has
    # not been run since the last data interval (or has been cleared). When catchup
    # is False, the scheduler creates a DAG run only for the latest interval.
    dag_catchup: bool = False

    # Maximum number of active DAG runs, beyond this number of DAG runs in a running
    # state, the scheduler won’t create new active DAG runs.
    dag_max_active_runs: int = 1

    # Task execution timeout - equivalent to the old 1-hour SLA
    # Tasks that exceed this duration will be failed
    task_execution_timeout: timedelta = timedelta(hours=1)

    # A function to be called when a task instance fails.
    dag_on_failure_callback: Optional[Callable] = None

    @property
    def dag_args(self) -> dict:
        """
        Return DAG arguments for DAG instantiation.

        Example:
            dag = DAG(**config.dag_args)
        """

        return {
            "dag_id": self.dag_id,
            "catchup": self.dag_catchup,
            "dagrun_timeout": self.dag_dagrun_timeout,
            "max_active_runs": self.dag_max_active_runs,
            "schedule": self.dag_schedule_interval,
            "start_date": self.dag_start_date,
            "description": self.description,
            "doc_md": self.description,
            "default_args": {
                "on_failure_callback": self.dag_on_failure_callback,
                "execution_timeout": self.task_execution_timeout,
            },
        }

    # ----------------------------------------------------------------------------------
    # Pipeline configuration parameters
    # ----------------------------------------------------------------------------------

    # Extended name of the pipeline suitable for print statements.
    pipeline_print_name: Optional[str] = None

    # Description of the pipeline used for DAG parameters `description` and `doc_md`.
    description: Optional[str] = None

    # Postgres username to be used for the pipeline.
    postgres_user: str = field(default=None, init=False)

    # Directory paths for data associated with the pipeline.
    data_dirs: ETLDataDirectories = field(default_factory=ETLDataDirectories)

    # Link to Superset dashboard.
    dashboard_link: Optional[str] = None

    # Regular expressions for the files to be moved to the process and store directories
    # during file ingestion, as implemented in the ingest() function of this module.
    process_format: Optional[str] = None
    store_format: Optional[str] = None

    # ----------------------------------------------------------------------------------

    def __post_init__(self):
        """
        Post-initialization for ETLConfig.

        Sets default values for pipeline_print_name, postgres_user, and data_dirs. Also
        validates that max_process_tasks and min_file_sets_in_batch are >= 1. Raises
        ValueError if configuration is invalid.
        """

        if not self.dag_id:
            raise ValueError("dag_id must not be empty.")
        if self.max_process_tasks < 1:
            raise ValueError("max_process_tasks must be >= 1")
        if self.min_file_sets_in_batch < 1:
            raise ValueError("min_file_sets_in_batch must be >= 1")
        if not issubclass(self.file_types, Enum):
            raise ValueError("file_types must be an Enum subclass.")
        if self.pipeline_print_name is None:
            self.pipeline_print_name = self.dag_id
        self.postgres_user = f"airflow_{self.dag_id}"
        self.data_dirs.set_paths(self.dag_id)

    def __str__(self):
        """
        Return a string representation of the ETLConfig.

        This is useful for logging and debugging purposes.
        """

        return (
            f"ETLConfig(dag_id={self.dag_id}, "
            f"pipeline_print_name={self.pipeline_print_name})"
        )
