"""Golden assertions for the demo run.

``demo/expected/golden_result.json`` records what must be true on *any* machine:
the plan shape, the row counts, which candidate wins, and the safety guarantees.
It records no timings, on purpose.  A golden file that pins a millisecond count
either rots on the next machine or gets rubber-stamped until it does; a run that
genuinely stops being fast enough fails its own threshold and says so instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest

pytestmark = pytest.mark.integration

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "demo" / "expected" / "golden_result.json"


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def diagnosis(demo_env: Any, golden_sql: str) -> Any:
    from schemapulse.engine import SchemaPulse

    return SchemaPulse(settings=demo_env).diagnose(golden_sql, provider="fixture")


# --------------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------------- #
def test_the_run_is_labelled_offline(diagnosis: Any, golden: dict[str, Any]) -> None:
    assert diagnosis.provider == golden["provider"]
    assert diagnosis.provider_is_live is golden["provider_is_live"]


def test_the_run_used_the_documented_threshold(diagnosis: Any, golden: dict[str, Any]) -> None:
    assert diagnosis.min_speedup == golden["min_speedup"]


# --------------------------------------------------------------------------- #
# the baseline evidence
# --------------------------------------------------------------------------- #
def test_baseline_plan_matches_the_golden_shape(diagnosis: Any, golden: dict[str, Any]) -> None:
    insight = diagnosis.insight
    expected = golden["insight"]
    assert sorted(insight.tables) == sorted(expected["tables"])
    assert insight.plan.plan_shape == expected["plan_shape"]
    assert len(insight.plan.nodes) == expected["node_count"]
    assert sorted(insight.plan.indexes_used) == sorted(expected["indexes_used"])


def test_row_counts_match_the_golden_values(diagnosis: Any, golden: dict[str, Any]) -> None:
    expected = golden["insight"]
    assert diagnosis.insight.plan.total_rows_examined == expected["total_rows_examined"]
    assert diagnosis.insight.plan.total_rows_produced == expected["total_rows_produced"]
    assert diagnosis.insight.rows_returned == 50


def test_hotspot_codes_match_the_golden_set(diagnosis: Any, golden: dict[str, Any]) -> None:
    codes = [h.code for h in diagnosis.insight.hotspots]
    assert codes == golden["insight"]["hotspot_codes"]


# --------------------------------------------------------------------------- #
# the recommendation
# --------------------------------------------------------------------------- #
def test_verdict_matches_the_golden_value(diagnosis: Any, golden: dict[str, Any]) -> None:
    assert diagnosis.verdict.value == golden["verdict"]


def test_the_winning_index_matches_the_golden_statement(
    diagnosis: Any, golden: dict[str, Any]
) -> None:
    assert diagnosis.verified is not None
    expected = golden["first_attempt"]
    assert diagnosis.verified.index_name == expected["index_name"]
    assert diagnosis.verified.statement == expected["statement"]
    assert diagnosis.verified.table == expected["table"]
    assert diagnosis.verified.columns == expected["columns"]
    assert diagnosis.verified.predicate == expected["predicate"]
    assert diagnosis.verified.predicate is not None  # it is a partial index


def test_plan_actually_changed(diagnosis: Any, golden: dict[str, Any]) -> None:
    comparison = diagnosis.comparison
    assert comparison is not None
    expected = golden["comparison"]
    assert comparison.plan_shape_changed is expected["plan_shape_changed"]
    assert comparison.seq_scan_removed is expected["seq_scan_removed"]
    assert comparison.sort_removed is expected["sort_removed"]
    assert comparison.index_added == expected["added_index"]
    assert comparison.rows_examined_delta == expected["rows_examined_delta"]


def test_the_speedup_is_believed_and_not_asserted(diagnosis: Any, golden: dict[str, Any]) -> None:
    """The golden file pins no timing, so the run must still clear its own bar."""
    speedup = diagnosis.speedup
    assert speedup is not None
    assert speedup >= diagnosis.min_speedup


def test_only_one_attempt_was_needed(diagnosis: Any) -> None:
    assert len(diagnosis.attempts) == 1
    assert diagnosis.best_attempt == 1


# --------------------------------------------------------------------------- #
# safety, verified against the live databases
# --------------------------------------------------------------------------- #
def _indexes(dsn: str, table: str = "orders") -> list[str]:
    with psycopg.connect(dsn) as conn:
        return sorted(
            row[0]
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = %s", (table,)
            ).fetchall()
        )


def test_target_database_kept_only_its_original_index(
    demo_env: Any, golden: dict[str, Any]
) -> None:
    assert _indexes(demo_env.database_url) == golden["safety"]["target_indexes_after_run"]


def test_shadow_database_was_cleaned_up(demo_env: Any, golden: dict[str, Any]) -> None:
    assert _indexes(demo_env.shadow_database_url) == golden["safety"]["shadow_indexes_after_run"]


def test_recommendation_is_for_a_human_to_run(diagnosis: Any, golden: dict[str, Any]) -> None:
    recommendation = diagnosis.recommendation
    assert recommendation is not None
    assert recommendation.auto_applied is golden["safety"]["recommendation_auto_applied"]
    assert "CONCURRENTLY" in recommendation.production_sql
    assert recommendation.warnings, "a partial index carries real deployment caveats"


def test_production_sql_names_the_index_that_was_measured(
    diagnosis: Any, golden: dict[str, Any]
) -> None:
    """The recommendation must not rename the index the evidence describes.

    A reader who runs the suggested SQL and finds a differently-named index
    than the one in the evidence table has been handed two different changes.
    """
    production_sql = diagnosis.recommendation.production_sql
    measured_name = golden["first_attempt"]["index_name"]
    assert measured_name in production_sql
    assert diagnosis.comparison.index_added == measured_name
