"""Phase 12 tests: health / mortality data integration & validation."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import health_data_service

DATA_URL = f"{settings.API_V1_PREFIX}/health-data"
VALIDATION_URL = f"{settings.API_V1_PREFIX}/health-data/validation"


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _reset_health_cache():
    health_data_service.reset_caches()
    yield
    health_data_service.reset_caches()


def _write_csv(path, rows, header="year,state,category,heat_wave_deaths,source"):
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


# --- Valid dataset loading ---------------------------------------------


def test_valid_dataset_loads() -> None:
    dataset = health_data_service.load_health_dataset()
    assert dataset["records_loaded_total"] > 0
    assert dataset["rejected_rows"] == 0


def test_dataset_loading_is_cached_not_reread(monkeypatch, tmp_path) -> None:
    path = tmp_path / "data.csv"
    _write_csv(path, ['2020,Testland,State,10,"Test Source"'])
    monkeypatch.setattr(settings, "HEALTH_DATA_CSV_PATH", str(path), raising=False)
    health_data_service.reset_caches()

    first = health_data_service.load_health_dataset()
    path.write_text("garbage that would fail to parse the same way", encoding="utf-8")
    second = health_data_service.load_health_dataset()
    assert first == second  # cached, not re-read


# --- Schema validation ---------------------------------------------------


def test_missing_dataset_file_raises_clearly(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        settings, "HEALTH_DATA_CSV_PATH", str(tmp_path / "missing.csv"), raising=False
    )
    health_data_service.reset_caches()
    with pytest.raises(health_data_service.HealthDataError):
        health_data_service.load_health_dataset()


def test_schema_mismatch_raises_clearly(monkeypatch, tmp_path) -> None:
    path = tmp_path / "bad_schema.csv"
    path.write_text("foo,bar\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(settings, "HEALTH_DATA_CSV_PATH", str(path), raising=False)
    health_data_service.reset_caches()
    with pytest.raises(health_data_service.HealthDataError) as excinfo:
        health_data_service.load_health_dataset()
    assert "schema" in str(excinfo.value.message).lower()


def test_each_observation_matches_the_declared_schema() -> None:
    for observation in health_data_service.list_observations():
        assert isinstance(observation["year"], int)
        assert isinstance(observation["state"], str) and observation["state"]
        assert isinstance(observation["heat_wave_deaths"], int)
        assert observation["heat_wave_deaths"] >= 0
        assert observation["source"]


# --- Source preservation ---------------------------------------------------


def test_source_is_preserved_verbatim() -> None:
    observations = health_data_service.list_observations(year=2022, state="Delhi")
    assert len(observations) == 1
    assert "Rajya Sabha" in observations[0]["source"]
    assert "Session 266" in observations[0]["source"]


def test_source_is_not_genericised(monkeypatch, tmp_path) -> None:
    path = tmp_path / "data.csv"
    _write_csv(
        path,
        ['2021,Testland,State,3,"A very specific citation, part (ii)"'],
    )
    monkeypatch.setattr(settings, "HEALTH_DATA_CSV_PATH", str(path), raising=False)
    health_data_service.reset_caches()
    observations = health_data_service.list_observations()
    assert observations[0]["source"] == "A very specific citation, part (ii)"


# --- Missing values ----------------------------------------------------


def test_missing_death_count_is_excluded_not_zero_filled(monkeypatch, tmp_path) -> None:
    path = tmp_path / "data.csv"
    _write_csv(
        path,
        [
            '2018,Ladakh,Union Territory,,"Source A"',
            '2019,Ladakh,Union Territory,NA,"Source A"',
            '2020,Ladakh,Union Territory,0,"Source A"',
        ],
    )
    monkeypatch.setattr(settings, "HEALTH_DATA_CSV_PATH", str(path), raising=False)
    health_data_service.reset_caches()
    dataset = health_data_service.load_health_dataset()
    assert dataset["missing_value_rows"] == 2
    assert dataset["records_loaded_total"] == 1
    assert dataset["observations"][0]["heat_wave_deaths"] == 0  # true zero kept


def test_bundled_dataset_has_known_missing_values() -> None:
    dataset = health_data_service.load_health_dataset()
    assert dataset["missing_value_rows"] >= 1


# --- Malformed rows -------------------------------------------------------


def test_malformed_rows_are_rejected_not_fatal(monkeypatch, tmp_path) -> None:
    path = tmp_path / "data.csv"
    _write_csv(
        path,
        [
            '2020,Testland,State,10,"Source A"',
            ',Testland,State,5,"Source A"',  # missing year
            '2020,,State,5,"Source A"',  # missing state
            '2020,Testland,State,-3,"Source A"',  # negative deaths
            '2020,Testland,State,not_a_number,"Source A"',  # non-numeric deaths
            'not_a_year,Testland,State,5,"Source A"',  # non-numeric year
        ],
    )
    monkeypatch.setattr(settings, "HEALTH_DATA_CSV_PATH", str(path), raising=False)
    health_data_service.reset_caches()
    dataset = health_data_service.load_health_dataset()
    assert dataset["records_loaded_total"] == 1
    assert dataset["rejected_rows"] == 5


# --- Duplicate handling ------------------------------------------------


def test_duplicate_year_state_is_deduplicated(monkeypatch, tmp_path) -> None:
    path = tmp_path / "data.csv"
    _write_csv(
        path,
        [
            '2020,Testland,State,10,"Source A"',
            '2020,Testland,State,99,"Source B (duplicate)"',
        ],
    )
    monkeypatch.setattr(settings, "HEALTH_DATA_CSV_PATH", str(path), raising=False)
    health_data_service.reset_caches()
    dataset = health_data_service.load_health_dataset()
    assert dataset["records_loaded_total"] == 1
    assert dataset["rejected_rows"] == 1
    assert dataset["observations"][0]["heat_wave_deaths"] == 10  # first kept


def test_bundled_dataset_has_no_duplicate_year_state_pairs() -> None:
    observations = health_data_service.list_observations()
    keys = [(o["year"], o["state"]) for o in observations]
    assert len(keys) == len(set(keys))


# --- Validation calculations ---------------------------------------------


def test_yearly_totals_match_the_source_data() -> None:
    """Cross-check against the original Rajya Sabha 'Total (All India)' row."""
    summary = health_data_service.summarise()
    totals = {row["year"]: row["total_deaths"] for row in summary["yearly_totals"]}
    assert totals[2018] == 890
    assert totals[2019] == 1274
    assert totals[2020] == 530
    assert totals[2021] == 374
    assert totals[2022] == 730


def test_high_risk_events_use_the_configured_threshold(monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "HEALTH_HIGH_RISK_DEATH_THRESHOLD", 1_000_000, raising=False
    )
    summary = health_data_service.summarise()
    assert summary["high_risk_events"] == 0


def test_top_regions_are_sorted_descending() -> None:
    summary = health_data_service.summarise()
    totals = [row["total_deaths"] for row in summary["top_regions"]]
    assert totals == sorted(totals, reverse=True)


def test_compare_predictions_to_observations_scores_correctly() -> None:
    """Uses clearly-synthetic, explicitly-labelled predictions, never real ones."""
    observations = [
        {"year": 2020, "state": "A", "heat_wave_deaths": 100},  # high risk
        {"year": 2020, "state": "B", "heat_wave_deaths": 1},  # low risk
        {"year": 2020, "state": "C", "heat_wave_deaths": 60},  # high risk
    ]
    predictions = [
        {"year": 2020, "state": "A", "high_risk": True},  # TP
        {"year": 2020, "state": "B", "high_risk": True},  # FP
        {"year": 2020, "state": "C", "high_risk": False},  # FN
    ]
    result = health_data_service.compare_predictions_to_observations(
        predictions, observations, high_risk_threshold=50
    )
    assert result["confusion_matrix"]["true_positive"] == 1
    assert result["confusion_matrix"]["false_positive"] == 1
    assert result["confusion_matrix"]["false_negative"] == 1
    assert result["probability_of_detection"] == pytest.approx(0.5)
    assert result["precision"] == pytest.approx(0.5)


# --- Insufficient data handling ---------------------------------------------


def test_validation_endpoint_defaults_to_descriptive_only() -> None:
    """No matched prediction series is bundled, so no skill metrics are invented."""
    summary = health_data_service.summarise()
    joined = " ".join(summary["notes"]).lower()
    assert "no model-predicted risk series" in joined or "fabricat" in joined


def test_compare_predictions_handles_no_matches() -> None:
    result = health_data_service.compare_predictions_to_observations(
        predictions=[{"year": 1900, "state": "Nowhere", "high_risk": True}],
        observations=health_data_service.list_observations(),
    )
    assert result["matched_observations"] == 0
    assert result["probability_of_detection"] is None
    assert result["precision"] is None


def test_summarise_handles_empty_observations() -> None:
    summary = health_data_service.summarise(observations=[])
    assert summary["observations"] == 0
    assert summary["yearly_totals"] == []
    assert summary["top_regions"] == []


def test_filtering_to_nonexistent_state_returns_empty_not_error() -> None:
    observations = health_data_service.list_observations(state="Narnia")
    assert observations == []
    summary = health_data_service.summarise(observations=observations)
    assert summary["observations"] == 0


# --- No fabricated values ---------------------------------------------------


def test_no_fabricated_values_known_real_figures() -> None:
    """Spot-check individual figures against the original CSV, verbatim."""
    def deaths(year: int, state: str) -> int:
        matches = health_data_service.list_observations(year=year, state=state)
        assert len(matches) == 1
        return matches[0]["heat_wave_deaths"]

    assert deaths(2019, "Bihar") == 215
    assert deaths(2022, "Punjab") == 130
    assert deaths(2019, "Assam") == 3
    assert deaths(2021, "Uttar Pradesh") == 35


def test_all_observations_marked_government_reported() -> None:
    for observation in health_data_service.list_observations():
        assert observation["data_status"] == "GOVERNMENT_REPORTED"


def test_compare_predictions_never_invents_a_prediction() -> None:
    """The comparator only ever scores predictions the caller supplies."""
    result = health_data_service.compare_predictions_to_observations(
        predictions=[], observations=health_data_service.list_observations()
    )
    assert result["matched_observations"] == 0


# --- Deterministic results --------------------------------------------------


def test_load_is_deterministic() -> None:
    health_data_service.reset_caches()
    first = health_data_service.load_health_dataset()
    health_data_service.reset_caches()
    second = health_data_service.load_health_dataset()
    assert first == second


def test_summarise_is_deterministic() -> None:
    assert health_data_service.summarise() == health_data_service.summarise()


# --- API ---------------------------------------------------------------


def test_health_data_endpoint(client: TestClient) -> None:
    response = client.get(DATA_URL, params={"state": "Kerala"})
    assert response.status_code == 200
    body = response.json()
    assert body["data_status"] == "GOVERNMENT_REPORTED"
    assert all(o["state"] == "Kerala" for o in body["observations"])
    assert body["records_returned"] == len(body["observations"])


def test_health_data_endpoint_filters_by_year(client: TestClient) -> None:
    response = client.get(DATA_URL, params={"year": 2022})
    assert response.status_code == 200
    body = response.json()
    assert all(o["year"] == 2022 for o in body["observations"])


def test_validation_endpoint(client: TestClient) -> None:
    response = client.get(VALIDATION_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "2018-2022"
    assert body["observations"] > 0
    assert "notes" in body


def test_validation_endpoint_year_range(client: TestClient) -> None:
    response = client.get(
        VALIDATION_URL, params={"year_from": 2020, "year_to": 2021}
    )
    assert response.status_code == 200
    body = response.json()
    years = {row["year"] for row in body["yearly_totals"]}
    assert years <= {2020, 2021}


def test_health_data_endpoints_in_schema(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/health-data" in paths
    assert "/api/v1/health-data/validation" in paths


def test_no_causal_or_mortality_reduction_claims(client: TestClient) -> None:
    response = client.get(VALIDATION_URL)
    joined = " ".join(response.json()["notes"]).lower()
    assert "causation" in joined or "not a causal" in joined
    assert "mortality reduction" not in joined
