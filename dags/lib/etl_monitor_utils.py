"""
ETL result tracking and database logging utilities for comprehensive pipeline
monitoring.

This module provides utilities for tracking Airflow ETL execution results and
persisting them to the database for monitoring and debugging purposes. It includes:
    - SQLAlchemy ORM models for ETL results tables.
    - Result record dataclasses for structured result entries.
    - ETLResult class for comprehensive result management and database I/O operations.
    - Integration with pipeline tasks for automatic result tracking.
    - Success and failure logging with detailed error information.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Union, Optional

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.orm import Session

from dags.lib.etl_config import ETLConfig
from dags.lib.logging_utils import LOGGER
from dags.lib.sql_utils import make_base, get_lens_engine, upsert_model_instances


# SQLAlchemy ORM base for infra_monitor schema.
InfraMonitorBase = make_base(schema="infra_monitor", include_update_ts=True)


class ETLResultSqla(InfraMonitorBase):
    """
    SQLAlchemy ORM model for the infra_monitor.airflow_etl_result table.
    """

    __tablename__ = "airflow_etl_result"

    dag_id: str = Column(String, primary_key=True)
    dag_run_id: str = Column(String, primary_key=True)
    dag_start_date: datetime = Column(DateTime, primary_key=True)
    file_name: str = Column(String, primary_key=True)
    success: bool = Column(Boolean, nullable=False)
    error_type: Optional[str] = Column(String)
    traceback: Optional[str] = Column(String)
    create_ts: Optional[datetime] = Column(DateTime)
    update_ts: Optional[datetime] = Column(DateTime)


@dataclass
class ETLResultRecord:
    """
    Data class representing the outcome of processing a data file in an ETL DAG run.

    Attributes:
    - file_name: Name of the file processed by the ETL task.
    - success: True if the ETL operation completed successfully for the file;
        otherwise False.
    - error_type: Short code or description indicating the type of error encountered
        during ETL processing.
    - traceback: Detailed traceback or error message if the ETL task failed.
    """

    file_name: str
    success: bool
    error_type: Optional[str]
    traceback: Optional[str]


class ETLResult:
    """
    Handles ETL results for Airflow DAG runs, including reading and writing results to
    the database.

    :param config: Configuration parameters for Airflow DAGs and pipeline tasks.
    :param dag_start_date: Timestamp indicating when the DAG run started.
    :param dag_run_id: Unique identifier of the Airflow DAG that executed the ETL task.
    :param exists: Whether the result already exists in the database; if so, read it in.
    """

    result_records: Dict[str, ETLResultRecord]

    def __init__(
        self,
        config: ETLConfig,
        dag_start_date: Union[datetime, str],
        dag_run_id: str,
        exists: bool = False,
    ):
        self.config = config
        self.dag_start_date = dag_start_date
        self.dag_run_id = dag_run_id
        self.result_records: Dict[str, ETLResultRecord] = {}
        self.engine = get_lens_engine(user=self.config.postgres_user, echo=False)
        if exists:
            self.read_existing_result()

    def read_existing_result(self) -> None:
        """
        Read existing ETL results for this DAG run from the database and populate
        `result_records`.
        """

        with Session(self.engine) as sess:
            records = (
                sess.query(ETLResultSqla)
                .filter(
                    ETLResultSqla.dag_id == self.config.dag_id,
                    ETLResultSqla.dag_run_id == self.dag_run_id,
                    ETLResultSqla.dag_start_date == self.dag_start_date,
                )
                .all()
            )
            self.result_records = {
                record.file_name: ETLResultRecord(
                    file_name=record.file_name,
                    success=record.success,
                    error_type=record.error_type,
                    traceback=record.traceback,
                )
                for record in records
            }

    def set_result_record(
        self,
        file_name: str,
        success: bool,
        error_type: Optional[str] = None,
        traceback: Optional[str] = None,
    ) -> None:
        """
        Set a result record for a processed file.

        :param file_name: Name of the file processed by the ETL task.
        :param success: True if the ETL operation completed successfully for the file;
            otherwise False.
        :param error_type: Short code or description indicating the type of error
            encountered during ETL processing.
        :param traceback: Detailed traceback or error message if the ETL task failed.
        """

        self.result_records[file_name] = ETLResultRecord(
            file_name=file_name,
            success=success,
            error_type=error_type,
            traceback=traceback,
        )

    @property
    def successes(self) -> list[ETLResultRecord]:
        """
        List of successfully processed file records.
        """

        return [record for record in self.result_records.values() if record.success]

    @property
    def errors(self) -> list[ETLResultRecord]:
        """
        List of file records that failed processing.
        """

        return [record for record in self.result_records.values() if not record.success]

    def submit(self) -> None:
        """
        Write the ETL results to the database using upsert logic.
        """

        model_instances = [
            ETLResultSqla(
                dag_id=self.config.dag_id,
                dag_run_id=self.dag_run_id,
                dag_start_date=self.dag_start_date,
                file_name=record.file_name,
                success=record.success,
                error_type=record.error_type,
                traceback=record.traceback,
            )
            for record in self.result_records.values()
        ]
        with Session(self.engine) as sess:
            # Executes an upsert with ON CONFLICT DO UPDATE to handle task retries.
            upsert_model_instances(
                session=sess,
                model_instances=model_instances,
                conflict_columns=[
                    col.name for col in ETLResultSqla.__table__.primary_key.columns
                ],
                on_conflict_update=True,
            )
            sess.commit()
        LOGGER.info(
            f"{len(self.successes)}/{len(self.result_records)} files processed "
            "successfully."
        )

    def __eq__(self, other: object) -> bool:
        """
        Equality comparison for ETLResult objects.
        """

        if not isinstance(other, ETLResult):
            return False
        return self.result_records == other.result_records
