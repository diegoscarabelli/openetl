"""
Unit tests for dags.pipelines.wid.process.

Covers the pure transform helpers and the WidProcessor orchestration (with the load
calls mocked, following the pipeline test convention of not hitting a real database).
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dags.lib.etl_config import ETLConfig
from dags.lib.filesystem_utils import FileSet
from dags.pipelines.wid.constants import WIDFileTypes
from dags.pipelines.wid.process import (
    WidProcessor,
    _populate_percentile_dimension,
    build_percentile_rows,
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


def test_variable_fields() -> None:
    """
    variable_fields unpacks the native code into its components (no percentile).
    """
    fields = variable_fields("sptincj992", "992", "j")
    assert fields["variable_code"] == "sptincj992"
    assert fields["series_type"] == "s"
    assert fields["concept"] == "ptinc"
    assert fields["age_code"] == "992"
    assert fields["pop_code"] == "j"
    assert "percentile" not in fields
    assert "sixlet" not in fields


def test_build_percentile_rows_ranges_and_points() -> None:
    """
    Ranges parse to their bracket; g-percentile points run to the next point, top to
    100.
    """
    rows = {
        row["percentile_code"]: row
        for row in build_percentile_rows(["p0p50", "p90p100", "p99", "p99.9", "p99.99"])
    }
    assert rows["p0p50"]["is_range"] is True
    assert rows["p0p50"]["lower_bound"] == Decimal("0")
    assert rows["p0p50"]["upper_bound"] == Decimal("50")
    assert rows["p0p50"]["width"] == Decimal("50")
    # Points are ordered so each runs up to the next; the top point runs to 100.
    assert rows["p99"]["is_range"] is False
    assert rows["p99"]["lower_bound"] == Decimal("99")
    assert rows["p99"]["upper_bound"] == Decimal("99.9")
    assert rows["p99.9"]["upper_bound"] == Decimal("99.99")
    assert rows["p99.99"]["upper_bound"] == Decimal("100")
    assert rows["p99.99"]["width"] == Decimal("100") - Decimal("99.99")


def test_build_percentile_rows_single_point_runs_to_100() -> None:
    """
    A lone g-percentile point runs up to 100 with a positive width.
    """
    (row,) = build_percentile_rows(["p99"])
    assert row["is_range"] is False
    assert row["lower_bound"] == Decimal("99")
    assert row["upper_bound"] == Decimal("100")
    assert row["width"] == Decimal("1")


def test_build_percentile_rows_rejects_unknown() -> None:
    """
    An unrecognized percentile code raises rather than loading a bad dimension row.
    """
    with pytest.raises(ValueError):
        build_percentile_rows(["not_a_percentile"])


def test_build_percentile_rows_zero_width_range() -> None:
    """
    A zero-width range (pXpX) is valid: it denotes a single percentile position.
    """
    (row,) = build_percentile_rows(["p31p31"])
    assert row["is_range"] is True
    assert row["lower_bound"] == Decimal("31")
    assert row["upper_bound"] == Decimal("31")
    assert row["width"] == Decimal("0")


def test_build_percentile_rows_rejects_inverted_range() -> None:
    """
    An inverted range (upper < lower) raises rather than violating the percentile CHECKs
    mid-finalize.
    """
    with pytest.raises(ValueError):
        build_percentile_rows(["p50p10"])


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
    iter_observations yields (country, variable, percentile, year, value); empty is
    None.
    """
    rows = list(iter_observations(_write_data(tmp_path)))
    assert rows[0] == ("AA", "sptincj992", "p99p100", "2019", "0.18")
    assert rows[2] == ("AA", "shwealj992", "p90p100", "2020", None)


def test_build_variable_rows(tmp_path: Path) -> None:
    """
    build_variable_rows returns distinct native codes with metadata attached.
    """
    meta = parse_metadata(_write_meta(tmp_path))
    rows = build_variable_rows(_write_data(tmp_path), meta)
    codes = {row["variable_code"] for row in rows}
    assert codes == {"sptincj992", "shwealj992"}
    by_code = {row["variable_code"]: row for row in rows}
    assert by_code["sptincj992"]["short_name"] == "Pre-tax"
    assert by_code["shwealj992"]["unit"] == "share"


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
    assert mock_copy.call_args.args[2] == [
        "country_code",
        "variable_code",
        "percentile_code",
        "year",
        "value",
    ]


def test_provenance_uses_country_variable_key(
    processor: WidProcessor, tmp_path: Path
) -> None:
    """
    Provenance is upserted on the (country_code, variable_code) key with native codes.
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
    ) as mock_upsert, patch("dags.pipelines.wid.process.copy_records"):
        processor.process_file_set(file_set, session)

    provenance_call = next(
        call
        for call in mock_upsert.call_args_list
        if type(call.kwargs["model_instances"][0]).__name__ == "Provenance"
    )
    assert provenance_call.kwargs["conflict_columns"] == [
        "country_code",
        "variable_code",
    ]
    codes = {inst.variable_code for inst in provenance_call.kwargs["model_instances"]}
    assert codes == {"sptincj992", "shwealj992"}


def test_provenance_skips_variables_absent_from_data(
    processor: WidProcessor, tmp_path: Path
) -> None:
    """
    A metadata variable with no data row is skipped, so the provenance -> variable FK
    holds.

    The metadata below lists an extra code (absent from the data file).
    """
    meta_path = tmp_path / "WID_metadata_AA_2026-01-01T00:00:00.000001Z.csv"
    meta_path.write_text(
        META_HEADER
        + "\n"
        + "AA;sptincj992;992;j;Aaland;Pre-tax;simple;tech;Share;Income shares;"
        + "esa;esa desc;Adults;20+;share;srcA;methodA;0.0\n"
        # Metadata for a variable that never appears in the data file.
        + "AA;absentj992;992;j;Aaland;Absent;d;t;X;X;esa;esa;Adults;20+;u;srcX;methX;0.1\n",
        encoding="utf-8",
    )
    file_set = FileSet(
        files={
            WIDFileTypes.OBSERVATIONS: [_write_data(tmp_path)],
            WIDFileTypes.VARIABLE_METADATA: [meta_path],
        }
    )
    session = MagicMock()
    with patch(
        "dags.pipelines.wid.process.upsert_model_instances"
    ) as mock_upsert, patch("dags.pipelines.wid.process.copy_records"):
        processor.process_file_set(file_set, session)

    provenance_call = next(
        call
        for call in mock_upsert.call_args_list
        if type(call.kwargs["model_instances"][0]).__name__ == "Provenance"
    )
    codes = {inst.variable_code for inst in provenance_call.kwargs["model_instances"]}
    assert "absentj992" not in codes
    assert codes == {"sptincj992"}


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


def test_populate_percentile_dimension() -> None:
    """
    _populate_percentile_dimension reads the distinct codes and upserts parsed rows.
    """
    session = MagicMock()
    session.execute.return_value = [("p0p100",), ("p99",), ("p99.9",)]
    with patch("dags.pipelines.wid.process.upsert_model_instances") as mock_upsert:
        _populate_percentile_dimension(session)

    instances = mock_upsert.call_args.kwargs["model_instances"]
    by_code = {inst.percentile_code: inst for inst in instances}
    assert by_code["p0p100"].is_range is True
    assert by_code["p0p100"].upper_bound == Decimal("100")
    assert by_code["p99"].is_range is False
    assert by_code["p99"].upper_bound == Decimal("99.9")
    assert by_code["p99.9"].upper_bound == Decimal("100")
    assert mock_upsert.call_args.kwargs["conflict_columns"] == ["percentile_code"]


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
        "DROP CONSTRAINT IF EXISTS observation_percentile_code_fkey" in sql
        for sql in executed
    )
    assert any(
        "DROP INDEX IF EXISTS wid.wid_observation_series_idx" in s for s in executed
    )
    assert any("TRUNCATE wid.observation" in sql for sql in executed)
    assert any("DELETE FROM wid.percentile" in sql for sql in executed)
    session.commit.assert_called_once()


def test_finalize_observation_table_rebuilds_constraints() -> None:
    """
    finalize_observation_table rebuilds the observation primary key, foreign keys, and
    index (after populating the percentile dimension).
    """
    session = MagicMock()
    session.execute.return_value = []
    with patch("dags.pipelines.wid.process.get_lens_engine"), patch(
        "dags.pipelines.wid.process.upsert_model_instances"
    ), patch("dags.pipelines.wid.process.Session") as mock_session_cls:
        mock_session_cls.return_value.__enter__.return_value = session
        finalize_observation_table("airflow_wid")

    executed = [str(call.args[0]) for call in session.execute.call_args_list]
    assert any("ADD CONSTRAINT observation_pkey PRIMARY KEY" in sql for sql in executed)
    assert any("observation_variable_code_fkey" in sql for sql in executed)
    assert any("observation_percentile_code_fkey" in sql for sql in executed)
    assert any(
        "SELECT DISTINCT percentile_code FROM wid.observation" in sql
        for sql in executed
    )
    assert any("CREATE INDEX wid_observation_series_idx" in sql for sql in executed)
    session.commit.assert_called_once()
