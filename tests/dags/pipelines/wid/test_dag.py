"""
Tests for the WID DAG wiring.
"""

from dags.pipelines.wid.dag import dag


def test_wid_dag_tasks_and_wiring() -> None:
    """
    The DAG wires the tasks in order: extract, ingest, batch, prepare, process,
    finalize, store.
    """
    assert set(dag.task_ids) == {
        "extract",
        "ingest",
        "batch",
        "prepare",
        "process",
        "finalize",
        "store",
    }

    extract_task = dag.get_task("extract")
    ingest_task = dag.get_task("ingest")
    assert "ingest" in extract_task.downstream_task_ids
    assert "extract" in ingest_task.upstream_task_ids

    # prepare runs before the load, finalize runs after it.
    assert "process" in dag.get_task("prepare").downstream_task_ids
    assert "finalize" in dag.get_task("process").downstream_task_ids
    assert "store" in dag.get_task("finalize").downstream_task_ids
