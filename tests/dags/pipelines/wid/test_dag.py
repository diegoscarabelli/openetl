"""
Tests for the WID DAG wiring.
"""

from dags.pipelines.wid.dag import dag


def test_wid_dag_tasks_and_wiring() -> None:
    """
    The DAG wires the five tasks in order: extract, ingest, batch, process, store.
    """
    assert set(dag.task_ids) == {"extract", "ingest", "batch", "process", "store"}

    extract_task = dag.get_task("extract")
    ingest_task = dag.get_task("ingest")
    assert "ingest" in extract_task.downstream_task_ids
    assert "extract" in ingest_task.upstream_task_ids
