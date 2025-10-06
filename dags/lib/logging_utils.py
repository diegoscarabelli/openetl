"""
Airflow-aware logging utilities for data pipeline tasks.

This module provides logging that automatically uses Airflow's native task logger when
running in an Airflow context, and falls back to standard Python logging otherwise. This
ensures clean, properly formatted logs in Airflow.
"""

import logging
from typing import Union

from airflow.sdk import get_current_context


class AirflowAwareLogger:
    """
    Logger that automatically uses Airflow's task logger when available.

    Detects if code is running within an Airflow task context and uses the task instance
    logger. Falls back to standard Python logging otherwise.
    """

    def __init__(self, name: str):
        """
        Initialize the logger.

        :param name: Logger name (typically __name__ of the module).
        """

        self.name = name
        self._fallback_logger = logging.getLogger(name)

    def _get_logger(self) -> logging.Logger:
        """
        Get the appropriate logger for the current context.

        :return: Task logger if in Airflow context, otherwise standard logger.
        """

        try:
            context = get_current_context()
            return context["task_instance"].log
        except (RuntimeError, KeyError, AttributeError):
            # Not in Airflow context, use fallback logger.
            return self._fallback_logger

    def debug(self, msg: Union[str, object], *args, **kwargs) -> None:
        """
        Log a debug message.
        """

        return self._get_logger().debug(msg, *args, **kwargs)

    def info(self, msg: Union[str, object], *args, **kwargs) -> None:
        """
        Log an info message.
        """

        return self._get_logger().info(msg, *args, **kwargs)

    def warning(self, msg: Union[str, object], *args, **kwargs) -> None:
        """
        Log a warning message.
        """

        return self._get_logger().warning(msg, *args, **kwargs)

    def error(self, msg: Union[str, object], *args, **kwargs) -> None:
        """
        Log an error message.
        """

        return self._get_logger().error(msg, *args, **kwargs)

    def critical(self, msg: Union[str, object], *args, **kwargs) -> None:
        """
        Log a critical message.
        """

        return self._get_logger().critical(msg, *args, **kwargs)


# Global logger instance for module-level imports.
LOGGER = AirflowAwareLogger(__name__)
