"""
Core utilities for Airflow DAG creation and ETL processing.

This module provides standard task functions for the ETL pipeline workflow,
including file ingestion, batching, processing, and storage operations. It includes:
    - Standard task functions: ingest(), batch(), process_wrapper(), store().
    - Abstract Processor base class for custom data processing logic.
    - create_dag() function for assembling complete DAGs from configuration.
    - Integration with ETLConfig for unified pipeline configuration.
"""

import random
import re
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from pprint import pformat
from shutil import move
from typing import Union

import pendulum
from airflow.exceptions import AirflowSkipException
from airflow.models import DAG
from airflow.providers.standard.operators.python import PythonOperator
from sqlalchemy.orm import Session

from dags.lib.etl_config import ETLConfig
from dags.lib.etl_monitor_utils import ETLResult
from dags.lib.filesystem_utils import DataState, FileSet
from dags.lib.logging_utils import LOGGER
from dags.lib.sql_utils import get_lens_engine


def ingest(config: ETLConfig, **context: dict) -> None:
    """
    Move files from the 'ingest' directory to the 'store' or 'process' directory,
    depending on which arguments are specified in the `config` parameter. Intended to be
    used as a PythonOperator callable in the `ingest` Airflow task.

    - Files matching `store_format` are moved to 'store' first.
    - Files matching `process_format` are moved to 'process' (if not already moved).
    - All remaining files are moved to 'process' only if `process_format` is not
      specified. Otherwise, files not matching either format remain in 'ingest'.

    :param config: Configuration parameters for Airflow DAGs and pipeline tasks.
    :param context: `op_kwargs` passed when defining the task in Airflow plus any
        additional Airflow keyword arguments automatically injected by Airflow.
        This parameter is not used in this function but is included to indicate
        the expected signature for replacement callables that may use it.
    """

    # Check existence of target directories.
    for state in [DataState.INGEST, DataState.PROCESS, DataState.STORE]:
        dir_path = getattr(config.data_dirs, state.value)
        if not dir_path.exists():
            raise FileNotFoundError(f"The '{state.value}' directory does not exist.")

    files = set(config.data_dirs.ingest.glob("*"))
    if not files:
        raise AirflowSkipException("No files found to ingest.")

    to_process = set()
    to_store = set()
    # First, move files matching `store_format` to 'store'.
    if config.store_format is not None:
        for file_path in list(files):
            filename = file_path.name
            if re.search(config.store_format, filename):
                dest = config.data_dirs.store / filename
                move(str(file_path), str(dest))
                to_store.add(filename)
                files.remove(file_path)
    # Then, move files matching `process_format` to process (if not already moved).
    if config.process_format is not None:
        for file_path in list(files):
            filename = file_path.name
            if re.search(config.process_format, filename):
                dest = config.data_dirs.process / filename
                move(str(file_path), str(dest))
                to_process.add(filename)
                files.remove(file_path)
    # Finally, move all remaining files to process only if `process_format` is not
    # specified.
    if config.process_format is None:
        for file_path in list(files):
            filename = file_path.name
            dest = config.data_dirs.process / filename
            move(str(file_path), str(dest))
            to_process.add(filename)
            files.remove(file_path)
    # Log the results.
    LOGGER.info(
        f"Ingest results:\n"
        f"Moved {len(to_process)} files to 'process': {sorted(to_process)}.\n"
        f"Moved {len(to_store)} files to 'store': {sorted(to_store)}.\n"
        f"Left {len(files)} files in 'ingest': "
        f"{sorted([f.name for f in files])}."
    )


def batch(config: ETLConfig, **context: dict) -> list[tuple[FileSet, ...]]:
    """
    Construct batches of file sets from the content of the 'process' directory. Intended
    to be used as a PythonOperator callable in the `batch` Airflow task.

    First, construct file sets by grouping files by their timestamp and matching them
    to a file type pattern.

    Then, split the file sets into batches, which will be processed concurrently
    (sequentially within each batch). The cardinality of file sets in each batch is
    determined by the `max_process_tasks` and `min_file_sets_in_batch` parameters of the
    pipeline configuration.

    :param config: Configuration parameters for Airflow DAGs and pipeline tasks.
    :param context: `op_kwargs` passed when defining the task in Airflow plus any
        additional Airflow keyword arguments automatically injected by Airflow. This
        parameter is not used in this function but is included to indicate the expected
        signature for replacement callables that may use it.
    :return: Batched file sets.
    """

    # ----------------------------------------------------------------------------------
    # Construct file sets
    # ----------------------------------------------------------------------------------

    if config.max_process_tasks <= 0:
        raise ValueError("`max_process_tasks` must be greater than 0.")

    if config.min_file_sets_in_batch <= 0:
        raise ValueError("`min_file_sets_in_batch` must be greater than 0.")

    file_paths = list(config.data_dirs.process.glob("*"))
    files_by_dt = {}
    # The timestamp is expected to be in the format
    # YYYY-MM-DDTHH:MM:SS.ssssss+00:00 or YYYY-MM-DDTHH:MM:SS+00:00.
    timestamp_regex = (
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:[+-]\d{2}:\d{2}|Z)?"
    )
    for file_path in file_paths:
        # To ensure we process files chronologically (which is often important
        # for optimal database performance), we attempt to parse a timestamp from the
        # filename. If no timestamp is found, use the file's last modified timestamp
        # with added jitter to avoid unintentional grouping of unrelated files.
        match = re.search(timestamp_regex, file_path.name)
        if match:
            dt = pendulum.parse(match.group(0))
        else:
            stat = file_path.stat()
            dt = pendulum.from_timestamp(stat.st_mtime).add(
                microseconds=random.randint(0, 999999)
            )
        files_by_dt.setdefault(dt, []).append(file_path)
    files_by_dt = {k: v for k, v in sorted(files_by_dt.items())}

    file_sets = []
    for dt, file_paths_to_group in files_by_dt.items():
        file_set = FileSet()
        for file_path in file_paths_to_group:
            for pattern in config.file_types:
                if re.search(pattern.value, file_path.name):
                    # Use enum object as key (provides access to both .name and .value)
                    if pattern not in file_set.files:
                        file_set.files[pattern] = []
                    file_set.files[pattern].append(file_path)
                    break  # Ensure each file is matched only once per file set.
        # Check that all files in file_paths_to_group were added to the file set.
        if set(file_set.file_paths) != set(file_paths_to_group):
            unmatched_files = [
                f.name for f in file_paths_to_group if f not in file_set.file_paths
            ]
            raise ValueError(
                f"Not all files for dt={dt} were included in the file set. "
                f"Unmatched files: {unmatched_files}."
            )
        if file_set.files:
            file_sets.append(file_set)

    if not file_sets:
        raise AirflowSkipException("No files found to process.")

    # ----------------------------------------------------------------------------------
    # Construct batches of file sets
    # ----------------------------------------------------------------------------------

    num_file_sets = len(file_sets)
    batches = []
    current_index = 0

    # Create batches by taking `min_file_sets_in_batch` file sets at a time
    # until we reach the maximum number of process tasks or run out of file sets.
    while (
        current_index + config.min_file_sets_in_batch <= num_file_sets
        and len(batches) < config.max_process_tasks
    ):
        batch = file_sets[current_index : current_index + config.min_file_sets_in_batch]
        batches.append(batch)
        current_index += config.min_file_sets_in_batch

    # Handle the case where no batches could be created.
    if not batches:
        batches = [file_sets]

    # Distribute the remaining items in a "round-robin" or cyclic distribution.
    remaining_file_sets = file_sets[current_index:]
    for i, file_set in enumerate(remaining_file_sets):
        batch_index = i % len(batches)
        batches[batch_index].append(file_set)

    # Convert FileSet objects to serializable format for XCom compatibility.
    serializable_batches = []
    for batch in batches:
        serializable_batch = [file_set.to_serializable() for file_set in batch]
        serializable_batches.append((serializable_batch,))

    return serializable_batches


class Processor(ABC):
    """
    Abstract base class for processing file sets in an ETL pipeline.
    """

    def __init__(
        self,
        config: ETLConfig,
        dag_run_id: str,
        dag_start_date: Union[datetime, str],
        file_sets: list[FileSet],
        **extra_processor_init_kwargs,
    ):
        """
        Initialize the Processor object.

        This class is responsible for processing files in the given file sets and
        updating the ETLResult object with the results. Each process operation should
        subclass this class and implement the process_file_set method to define the
        specific processing logic.

        :param config: Configuration parameters for Airflow DAGs and pipeline tasks.
        :param dag_run_id: Unique identifier of the Airflow DAG that executed the ETL
            task.
        :param dag_start_date: Timestamp indicating when the DAG run started.
        :param file_sets: Batch of FileSet objects to process.
        :param extra_processor_init_kwargs: Additional keyword arguments to be passed to
            the processor class when called by process_wrapper function.
        """

        self.config = config
        self.dag_run_id = dag_run_id
        self.dag_start_date = dag_start_date
        self.file_sets = file_sets
        self.extra_processor_init_kwargs = extra_processor_init_kwargs
        self._init_results()

    def _init_results(self):
        """
        Initialize the ETLResult object.
        """

        self.results = ETLResult(
            config=self.config,
            dag_run_id=self.dag_run_id,
            dag_start_date=self.dag_start_date,
        )
        for file_set in self.file_sets:
            for file in file_set.file_paths:
                self.results.set_result_record(
                    file_name=file.name, success=False, error_type=None, traceback=None
                )

    def process(self):
        """
        Process the files in each file set and submit the ETL results to the database.

        Each file set is processed in its own session/transaction for independence and
        resilience.
        """

        pg_engine = get_lens_engine(user=self.config.postgres_user)

        # Process each file set in its own session/transaction.
        for file_set in self.file_sets:
            with Session(pg_engine, autoflush=self.config.autoflush) as sess:
                self.prepare_session(session=sess)
                self._try_process_file_set(file_set=file_set, session=sess)

        # Submit the ETL results.
        self.results.submit()

    def prepare_session(self, session: Session):
        """
        Prepare the session for processing the files in the file sets.

        Override this method to add any additional logic to the session before
        processing the files (e.g., creating caches, etc.).

        :param session: SQLAlchemy Session object.
        """

        return

    def _try_process_file_set(self, file_set: FileSet, session: Session):
        """
        Attempt to process the file set and submit the data to the database.

        Successes and failures are recorded in the ETL results.

        :param file_set: FileSet to process.
        :param session: SQLAlchemy Session object.
        """

        try:
            LOGGER.info(f"Processing file set:\n{pformat(file_set.file_paths)}")
            self.process_file_set(file_set=file_set, session=session)
            session.commit()
            for file in file_set.file_paths:
                self.results.set_result_record(file_name=file.name, success=True)
            LOGGER.info("File set processed successfully.")
        except Exception as e:
            LOGGER.error(traceback.format_exc())
            LOGGER.info("Rolling back database transaction.")
            session.rollback()
            for file in file_set.file_paths:
                self.results.set_result_record(
                    file_name=file.name,
                    success=False,
                    error_type=str(e.args[0]) if e.args else str(e),
                    traceback=traceback.format_exc(limit=1),
                )

    @abstractmethod
    def process_file_set(self, file_set: FileSet, session: Session):
        """
        Process the `file_set` in the session.

        Override this method to implement the processing logic for the files in the file
        set.

        :param file_set: FileSet to process.
        :param session: SQLAlchemy Session object.
        """

        raise NotImplementedError


def process_wrapper(
    serialized_file_sets: list[dict],
    config: ETLConfig,
    dag_run_id: str,
    dag_start_date: Union[datetime, str],
    **context,
) -> None:
    """
    Wrapper function to process file sets in a batch. Intended to be used as a
    PythonOperator callable in each `process` Airflow task assigned to each batch of
    file sets.

    :param serialized_file_sets: List of serialized file sets in the batch to process.
    :param config: Configuration parameters for Airflow DAGs and pipeline tasks.
    :param dag_run_id: Unique identifier of the Airflow DAG that executed the ETL task.
    :param dag_start_date: Timestamp indicating when the DAG run started.
    :param context: `op_kwargs` passed when defining the task in Airflow plus any
        additional Airflow keyword arguments automatically injected by Airflow.
    """

    # Deserialize file sets from XCom data.
    file_sets = []
    for serialized_file_set in serialized_file_sets:
        file_set = FileSet.from_serializable(serialized_file_set, config.file_types)
        file_sets.append(file_set)

    LOGGER.info(f"Processing {len(file_sets)} file sets in this batch.")

    # Construct a dictionary with runtime values of extra_processor_init_kwargs
    # from the `context` which was populated via `op_kwargs` in the 'process' task
    # definition which uses this callable. `context` might contain more keywords than
    # those defined in config.extra_processor_init_kwargs (injected at runtime by
    # Airflow), so filter them.
    extra_processor_init_kwargs = {
        k: context.get(k)
        for k in getattr(config, "extra_processor_init_kwargs", {}).keys()
    }
    processor = config.processor_class(
        config=config,
        dag_run_id=dag_run_id,
        dag_start_date=dag_start_date,
        file_sets=file_sets,
        **extra_processor_init_kwargs,
    )
    processor.process()


def store(
    config: ETLConfig,
    dag_run_id: str,
    dag_start_date: Union[datetime, str],
    **context: dict,
) -> None:
    """
    Move all files from the 'process' directory to the 'store' directory. Files that
    failed processing (according to the ETLResult persisted to the database) are moved
    to the 'quarantine' directory. Intended to be used as a PythonOperator callable in
    the `store` Airflow task.

    :param config: Configuration parameters for Airflow DAGs and pipeline tasks.
    :param dag_run_id: Unique identifier of the Airflow DAG that executed the ETL task.
    :param dag_start_date: Timestamp indicating when the DAG run started.
    :param context: `op_kwargs` passed when defining the task in Airflow plus any
        additional Airflow keyword arguments automatically injected by Airflow. This
        parameter is not used in this function but is included to indicate the expected
        signature for replacement callables that may use it.
    """

    # Check existence of target directories.
    for state in [DataState.PROCESS, DataState.STORE, DataState.QUARANTINE]:
        dir_path = getattr(config.data_dirs, state.value)
        if not Path(dir_path).exists():
            raise FileNotFoundError(f"The '{state.value}' directory does not exist.")

    # Read the ETL processing report for this DAG run.
    etl_result = ETLResult(config, dag_start_date, dag_run_id, exists=True)

    files = list(config.data_dirs.process.glob("*"))
    to_store = set()
    to_quarantine = set()

    for file_path in files:
        filename = file_path.name
        if any(record.file_name == filename for record in etl_result.errors):
            dest = config.data_dirs.quarantine / filename
            move(str(file_path), str(dest))
            to_quarantine.add(filename)
        else:
            dest = config.data_dirs.store / filename
            move(str(file_path), str(dest))
            to_store.add(filename)

    LOGGER.info(
        "Store results:\n"
        f"Moved {len(to_store)} files to 'store': {sorted(to_store)}.\n"
        f"Moved {len(to_quarantine)} files to 'quarantine': "
        f"{sorted(to_quarantine)}."
    )


def create_dag(config: ETLConfig, apply_default_task_sequence: bool = True) -> DAG:
    """
    Generate an Airflow DAG object for the pipeline using the configuration.

    Uses the task python callables defined in this module. The extra keyword arguments
    are passed to the task callables via the `op_kwargs` parameter in order to allow
    dynamic configuration of the tasks at runtime (such as Jinja templated fields).

    If you want to set a different order for the tasks (or include additional tasks),
    you can do the following:

    1. Turn off `apply_default_task_sequence` to prevent the default task order from
        being set.
    2. Use `dag.get_task(<task_id>)` to get a task by its ID and set the order
       using `task1 >> task2`.

    :param config: Configuration parameters for Airflow DAGs and pipeline tasks.
    :param apply_default_task_sequence: If True, sets the default task dependency
        sequence.
    :return: An Airflow DAG object configured with the tasks defined in this module.
    """

    dag = DAG(**config.dag_args)

    with dag:
        task_ingest = PythonOperator(
            task_id="ingest",
            python_callable=config.ingest_callable or ingest,
            op_kwargs={"config": config, **config.extra_ingest_kwargs},
            doc_md=(
                f"Move files with data to process from the "
                f"{config.data_dirs.ingest} directory to the "
                f"{config.data_dirs.process} or {config.data_dirs.store} directory, "
                f"depending on which arguments are specified in the config "
                f"parameter."
            ),
        )

        task_batch = PythonOperator(
            task_id="batch",
            python_callable=config.batch_callable or batch,
            op_kwargs={"config": config, **config.extra_batch_kwargs},
            doc_md=(
                "Construct batches of file sets from the content of the "
                f"{config.data_dirs.process} directory."
            ),
        )

        task_process = PythonOperator.partial(
            task_id="process",
            python_callable=process_wrapper,
            op_kwargs={
                "config": config,
                "dag_run_id": "{{ dag_run.run_id }}",
                "dag_start_date": "{{ dag_run.start_date }}",
                **config.extra_processor_init_kwargs,
            },
            doc_md=(
                "Dynamically generate one or more concurrent Airflow tasks, each "
                "of which processes a batch of file sets sequentially. This task "
                "extracts, validates, and inserts the data to the SQL database "
                "resources associated with this pipeline. It also inserts the ETL "
                "processing results for each file."
            ),
        ).expand(
            # Passes a list of file sets (a batch) to process_wrapper.
            op_args=task_batch.output
        )

        task_store = PythonOperator(
            task_id="store",
            python_callable=config.store_callable or store,
            op_kwargs={
                "config": config,
                "dag_run_id": "{{ dag_run.run_id }}",
                "dag_start_date": "{{ dag_run.start_date }}",
                **config.extra_store_kwargs,
            },
            doc_md=(
                f"Move all files from the {config.data_dirs.process} directory to "
                f"the {config.data_dirs.store} directory, except those that failed "
                f"processing (according to the ETLResult persisted to the "
                f"database), which are moved to the {config.data_dirs.quarantine} "
                f"directory."
            ),
        )

        if apply_default_task_sequence:
            task_ingest >> task_batch >> task_process >> task_store

    return dag
