"""
Unit tests for dags.pipelines.wid.process.

Covers the pure transform helpers and the WidProcessor orchestration (with the load
calls mocked, following the pipeline test convention of not hitting a real database).
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dags.lib.etl_config import ETLConfig
from dags.lib.filesystem_utils import FileSet
from dags.pipelines.wid.constants import WIDFileTypes
from dags.pipelines.wid.process import (
    WidProcessor,
    build_variable_code,
    build_variable_rows,
    finalize_observation_table,
    first_country,
    iter_observations,
    parse_countries,
    parse_metadata,
    prepare_observation_table,
    variable_fields,
)

DATA_HEADER = "country;variable;percentile;year;value;age;pop"
META_HEADER = (
    "country;variable;age;pop;countryname;shortname;simpledes;technicaldes;"
    "shorttype;longtype;shortpop;longpop;shortage;longage;unit;source;method;"
    "data_quality_score"
)


def _write_data(tmp_path: Path) -> Path:
    path = tmp_path / "WID_data_AA_2026-01-01T00:00:00.000001Z.csv"
    path.write_text(
        DATA_HEADER
        + "\n"
        + "AA;sptincj992;p99p100;2019;0.18;992;j\n"
        + "AA;sptincj992;p99p100;2020;0.19;992;j\n"
        + "AA;shwealj992;p90p100;2020;;992;j\n",
        encoding="utf-8",
    )
    return path


def _write_meta(tmp_path: Path) -> Path:
    path = tmp_path / "WID_metadata_AA_2026-01-01T00:00:00.000001Z.csv"
    path.write_text(
        META_HEADER
        + "\n"
        + "AA;sptincj992;992;j;Aaland;Pre-tax;simple;tech;Share;Income shares;"
        + "esa;esa desc;Adults;20+;share;srcA;methodA;0.0\n"
        + "AA;shwealj992;992;j;Aaland;Wealth;wsimple;wtech;Share;Wealth shares;"
        + "esa;esa desc;Adults;20+;share;srcB;methodB;1.0\n",
        encoding="utf-8",
    )
    return path


def _write_countries(tmp_path: Path) -> Path:
    path = tmp_path / "WID_countries_2026-01-01T00:00:00.000009Z.csv"
    path.write_text(
        "alpha2;titlename;shortname;region;region2\n"
        + "AA;the Aaland;Aaland;Europe;Northern Europe\n",
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------------------
# Transform helpers
# --------------------------------------------------------------------------------------


def test_build_variable_code() -> None:
    """
    The fully qualified code is sixlet_percentile_age_pop.
    """
    assert build_variable_code("sptincj992", "p99p100", "992", "j") == (
        "sptinc_p99p100_992_j"
    )


def test_variable_fields() -> None:
    """
    variable_fields unpacks the code into its components.
    """
    fields = variable_fields("sptincj992", "p99p100", "992", "j")
    assert fields["fully_qualified_code"] == "sptinc_p99p100_992_j"
    assert fields["sixlet"] == "sptinc"
    assert fields["series_type"] == "s"
    assert fields["concept"] == "ptinc"
    assert fields["percentile"] == "p99p100"
    assert fields["age_code"] == "992"
    assert fields["pop_code"] == "j"


def test_parse_metadata(tmp_path: Path) -> None:
    """
    parse_metadata keys by (sixlet, age, pop) and coerces the quality score.
    """
    meta = parse_metadata(_write_meta(tmp_path))
    entry = meta[("sptinc", "992", "j")]
    assert entry["short_name"] == "Pre-tax"
    assert entry["description"] == "simple"
    assert entry["unit"] == "share"
    assert entry["source"] == "srcA"
    assert entry["data_quality_score"] == 0.0
    assert entry["country"] == "AA"


def test_parse_countries(tmp_path: Path) -> None:
    """
    parse_countries maps alpha2/titlename/region.
    """
    records = parse_countries(_write_countries(tmp_path))
    assert records == [{"country_code": "AA", "name": "the Aaland", "region": "Europe"}]


def test_first_country(tmp_path: Path) -> None:
    """
    first_country returns the country of the first data row.
    """
    assert first_country(_write_data(tmp_path)) == "AA"


def test_iter_observations(tmp_path: Path) -> None:
    """
    iter_observations yields (country, code, year, value); empty value is None.
    """
    rows = list(iter_observations(_write_data(tmp_path)))
    assert rows[0] == ("AA", "sptinc_p99p100_992_j", "2019", "0.18")
    assert rows[2] == ("AA", "shweal_p90p100_992_j", "2020", None)


def test_build_variable_rows(tmp_path: Path) -> None:
    """
    build_variable_rows returns distinct codes with metadata attached.
    """
    meta = parse_metadata(_write_meta(tmp_path))
    rows = build_variable_rows(_write_data(tmp_path), meta)
    codes = {row["fully_qualified_code"] for row in rows}
    assert codes == {"sptinc_p99p100_992_j", "shweal_p90p100_992_j"}
    by_code = {row["fully_qualified_code"]: row for row in rows}
    assert by_code["sptinc_p99p100_992_j"]["short_name"] == "Pre-tax"
    assert by_code["shweal_p90p100_992_j"]["unit"] == "share"


# --------------------------------------------------------------------------------------
# WidProcessor
# --------------------------------------------------------------------------------------


@pytest.fixture
def processor() -> WidProcessor:
    """
    Build a WidProcessor with a mocked config and ETLResult.

    :return: WidProcessor instance.
    """
    config = MagicMock(spec=ETLConfig)
    with patch("dags.lib.dag_utils.ETLResult"):
        return WidProcessor(
            config=config,
            dag_run_id="test_run",
            dag_start_date=datetime(2025, 1, 1),
            file_sets=[],
        )


def test_country_fileset_upserts_and_copies(
    processor: WidProcessor, tmp_path: Path
) -> None:
    """
    A country FileSet upserts country, variables, and provenance, then appends
    observations with COPY (no per-country DELETE; the table is truncated in prepare).
    """
    file_set = FileSet(
        files={
            WIDFileTypes.OBSERVATIONS: [_write_data(tmp_path)],
            WIDFileTypes.VARIABLE_METADATA: [_write_meta(tmp_path)],
        }
    )
    session = MagicMock()
    with patch(
        "dags.pipelines.wid.process.upsert_model_instances"
    ) as mock_upsert, patch("dags.pipelines.wid.process.copy_records") as mock_copy:
        processor.process_file_set(file_set, session)

    upserted_models = [
        type(call.kwargs["model_instances"][0]).__name__
        for call in mock_upsert.call_args_list
    ]
    assert "Country" in upserted_models
    assert "Variable" in upserted_models
    assert "Provenance" in upserted_models

    mock_copy.assert_called_once()
    assert mock_copy.call_args.args[1] == "wid.observation"


def test_countries_fileset_upserts_names(
    processor: WidProcessor, tmp_path: Path
) -> None:
    """
    A countries FileSet upserts country names and regions, and does not COPY.
    """
    file_set = FileSet(files={WIDFileTypes.COUNTRIES: [_write_countries(tmp_path)]})
    session = MagicMock()
    with patch(
        "dags.pipelines.wid.process.upsert_model_instances"
    ) as mock_upsert, patch("dags.pipelines.wid.process.copy_records") as mock_copy:
        processor.process_file_set(file_set, session)

    mock_upsert.assert_called_once()
    instance = mock_upsert.call_args.kwargs["model_instances"][0]
    assert type(instance).__name__ == "Country"
    assert instance.name == "the Aaland"
    assert instance.region == "Europe"
    mock_copy.assert_not_called()


def test_prepare_observation_table_drops_and_truncates() -> None:
    """
    prepare_observation_table drops the observation constraints and truncates it.
    """
    session = MagicMock()
    with patch("dags.pipelines.wid.process.get_lens_engine"), patch(
        "dags.pipelines.wid.process.Session"
    ) as mock_session_cls:
        mock_session_cls.return_value.__enter__.return_value = session
        prepare_observation_table("airflow_wid")

    executed = [str(call.args[0]) for call in session.execute.call_args_list]
    assert any("DROP CONSTRAINT IF EXISTS observation_pkey" in sql for sql in executed)
    assert any(
        "DROP INDEX IF EXISTS wid.wid_observation_variable_idx" in s for s in executed
    )
    assert any("TRUNCATE wid.observation" in sql for sql in executed)
    session.commit.assert_called_once()


def test_finalize_observation_table_rebuilds_constraints() -> None:
    """
    finalize_observation_table rebuilds the observation primary key and foreign keys.
    """
    session = MagicMock()
    with patch("dags.pipelines.wid.process.get_lens_engine"), patch(
        "dags.pipelines.wid.process.Session"
    ) as mock_session_cls:
        mock_session_cls.return_value.__enter__.return_value = session
        finalize_observation_table("airflow_wid")

    executed = [str(call.args[0]) for call in session.execute.call_args_list]
    assert any("ADD CONSTRAINT observation_pkey PRIMARY KEY" in sql for sql in executed)
    assert any("observation_variable_code_fkey" in sql for sql in executed)
    assert any("CREATE INDEX wid_observation_variable_idx" in sql for sql in executed)
    session.commit.assert_called_once()
