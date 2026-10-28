"""Round 4 tests: sentiment pack, corpus, extraction, index,
forecast integration, commentary claims, API, intent isolation."""

from __future__ import annotations

import ast
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fmcg_forecast.api import create_app
from fmcg_forecast.forecast.service import (
    CommentaryVerificationError,
    ForecastService,
)
from fmcg_forecast.forecast.verify import verify_forecast
from fmcg_forecast.modelport import OfflineModel
from fmcg_forecast.sentiment.corpus import expected_reading, generate_sentiment_corpus
from fmcg_forecast.sentiment.extract import build_extraction, extract_headline
from fmcg_forecast.sentiment.grading import build_sentiment_grading_store
from fmcg_forecast.sentiment.index import compute_index
from fmcg_forecast.sentiment.load import load_sentiment_corpus
from fmcg_forecast.sentiment.models import SentimentItem
from fmcg_forecast.sentiment.pack import SENTIMENT_PACK_V1, load_sentiment_pack
from fmcg_forecast.sentiment.service import SentimentConflictError, SentimentService
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

SEED = 20261027
PACK = SENTIMENT_PACK_V1


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("r4") / "test.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    grading = build_sentiment_grading_store(db)
    load_state = load_sentiment_corpus(store, grading, SEED)
    sentiment = SentimentService(store, OfflineModel())
    pipeline = sentiment.run_pipeline()
    return {
        "db": db,
        "store": store,
        "grading": grading,
        "sentiment": sentiment,
        "load_state": load_state,
        "pipeline": pipeline,
    }


# --- the pack ------------------------------------------------------------


def test_pack_loader_is_fail_closed():
    assert load_sentiment_pack().version == "2026.10.1"
    assert load_sentiment_pack("2026.10.1").version == "2026.10.1"
    with pytest.raises(ValueError):
        load_sentiment_pack("1999.01.1")


def test_pack_lexicon_is_well_formed():
    aspects = {e.aspect for e in PACK.lexicon}
    assert aspects == {"policy", "supply", "demand", "weather", "trade"}
    assert all(e.polarity in (-1, 1) for e in PACK.lexicon)
    assert all(e.weight in (1, 2) for e in PACK.lexicon)
    assert len({e.phrase for e in PACK.lexicon}) == len(PACK.lexicon)


# --- extraction: hand-worked fixtures -------------------------------------


def test_extraction_single_phrase_reads_half_step():
    reading = extract_headline("Ministry release: support price hike announced", PACK)
    assert reading["status"] == "classified"
    assert reading["score"] == 2
    assert reading["direction"] == 0.5
    assert reading["strength"] == 0.5
    assert reading["aspects"] == {"policy": 2}
    assert reading["matched_phrases"] == ["support price hike"]


def test_extraction_two_phrases_reach_full_step():
    reading = extract_headline(
        "Support price hike with export demand strong across ports", PACK
    )
    assert reading["score"] == 4
    assert reading["direction"] == 1.0
    assert reading["strength"] == 1.0
    assert reading["aspects"] == {"policy": 2, "demand": 2}


def test_extraction_negative_direction():
    reading = extract_headline("Trade wire: export ban imposed on shipments", PACK)
    assert reading["score"] == -2
    assert reading["direction"] == -0.5
    assert reading["strength"] == 0.5
    assert reading["aspects"] == {"policy": -2}


def test_extraction_cancelling_signals_are_unclassified_never_forced():
    reading = extract_headline("Arrivals surge while export demand strong", PACK)
    assert reading["status"] == "unclassified"
    assert reading["direction"] is None
    assert "cancel" in reading["reason"]


def test_extraction_signalless_headline_is_unclassified():
    reading = extract_headline("Committee reviews the procurement calendar", PACK)
    assert reading["status"] == "unclassified"
    assert reading["direction"] is None
    assert reading["matched_phrases"] == []


def test_extraction_via_model_port_matches_the_rule():
    via_port = OfflineModel().extract_sentiment(
        headline="Support price hike with export demand strong across ports"
    )
    direct = extract_headline(
        "Support price hike with export demand strong across ports", PACK
    )
    assert via_port == direct


# --- the index: hand-computed fixture --------------------------------------


def _item(item_id: str, day: date, headline: str) -> SentimentItem:
    return SentimentItem(
        item_id=item_id,
        commodity="wheat",
        item_date=day,
        source="trade wire",
        headline=headline,
    )


def test_index_hand_computed_with_decay():
    # Week Mon 2025-06-02 .. Sun 2025-06-08; window ends at the Sunday.
    fresh = _item("NEWS-2099-001", date(2025, 6, 8), "support price hike")
    older = _item("NEWS-2099-002", date(2025, 6, 1), "buyer demand weak")
    extractions = [
        build_extraction(fresh, extract_headline(fresh.headline, PACK), PACK, "offline"),
        build_extraction(older, extract_headline(older.headline, PACK), PACK, "offline"),
    ]
    # fresh: direction +0.5, strength 0.5, age 0 -> weight 0.5
    # older: direction -0.5, strength 0.5, age 7 -> weight 0.5 * 0.5 = 0.25
    # value = (0.5*0.5 + -0.5*0.25) / 0.75 = 0.125 / 0.75 = 0.1667
    index = compute_index("wheat", date(2025, 6, 2), extractions, PACK)
    assert index is not None
    assert index.value == 0.1667
    assert index.n_items == 2
    assert index.aspect_values == {"policy": 0.5, "demand": -0.5}
    # a later week whose window holds neither item has NO index
    assert compute_index("wheat", date(2025, 6, 23), extractions, PACK) is None


# --- the corpus -------------------------------------------------------------


def test_corpus_loads_with_the_planted_shape(env):
    manifest = env["store"].get_sentiment_manifest()
    assert manifest is not None
    assert manifest.item_count == 583
    assert manifest.per_commodity["coffee"] == 4
    assert manifest.per_commodity["groundnut"] == 12
    assert env["load_state"]["already_loaded"] is False
    again = load_sentiment_corpus(env["store"], env["grading"], SEED)
    assert again["already_loaded"] is True
    assert again["items_written"] == 0


def test_corpus_planted_clarity_counts(env):
    intents = env["grading"].list_intents()
    assert len(intents) == 583
    clarity = {}
    for intent in intents:
        clarity[intent.clarity] = clarity.get(intent.clarity, 0) + 1
    assert clarity == {"clear": 485, "ambiguous": 50, "none": 48}


def test_corpus_generation_is_deterministic():
    first = generate_sentiment_corpus(SEED)
    second = generate_sentiment_corpus(SEED)
    assert [i.item_id for i in first.items] == [i.item_id for i in second.items]
    assert [i.headline for i in first.items] == [i.headline for i in second.items]
    assert first.manifest.digest == second.manifest.digest


def test_full_corpus_extraction_matches_planted_intent(env):
    """The R4 grading core: every stored extraction, exact, vs intent."""
    extractions = env["sentiment"].list_extractions()
    assert len(extractions) == 583
    for extraction in extractions:
        intent = env["grading"].get_intent(extraction.item_id)
        expected = expected_reading(intent)
        assert extraction.status == expected["status"], extraction.item_id
        if expected["status"] == "classified":
            assert extraction.direction == expected["direction"], extraction.item_id
            assert extraction.strength == expected["strength"], extraction.item_id
            assert extraction.score == expected["score"], extraction.item_id
            assert extraction.aspects == expected["aspects"], extraction.item_id
        else:
            # ambiguous and signalless items land unclassified, graded
            assert extraction.direction is None, extraction.item_id
            assert extraction.reason, extraction.item_id


def test_unclassified_count_is_the_planted_ambiguous_plus_none(env):
    assert env["pipeline"]["unclassified"] == 98


# --- the pipeline ------------------------------------------------------------


def test_pipeline_is_idempotent(env):
    again = env["sentiment"].run_pipeline()
    assert again["extractions_new"] == 0
    assert again["indices_new"] == 0
    assert again["items"] == 583


def test_every_stored_index_reperforms(env):
    assert env["sentiment"].verify_stored() == {"problems": []}
    indices = env["sentiment"].list_indices("wheat")
    assert len(indices) > 100
    extractions = env["sentiment"].list_extractions("wheat")
    for index in indices:
        recomputed = compute_index("wheat", index.week_start, extractions, PACK)
        assert recomputed is not None
        assert recomputed.value == index.value
        assert recomputed.index_id == index.index_id


def test_tampered_extraction_is_caught(tmp_path):
    db = str(tmp_path / "tamper.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    grading = build_sentiment_grading_store(db)
    load_sentiment_corpus(store, grading, SEED)
    sentiment = SentimentService(store, OfflineModel())
    sentiment.run_pipeline()
    assert sentiment.verify_stored() == {"problems": []}

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT item_id, payload FROM sentiment_extractions "
        "WHERE payload LIKE '%\"direction\":0.5%' LIMIT 1"
    ).fetchone()
    item_id, payload = row
    tampered = json.loads(payload)
    tampered["direction"] = -0.5
    conn.execute(
        "UPDATE sentiment_extractions SET payload = ? WHERE item_id = ?",
        (json.dumps(tampered), item_id),
    )
    conn.commit()
    conn.close()

    problems = sentiment.verify_stored()["problems"]
    assert problems, "the tampered extraction must be caught"
    assert any("content id mismatch" in p for p in problems)
    with pytest.raises(SentimentConflictError):
        sentiment.run_pipeline()


# --- forecast integration -----------------------------------------------------


def _wired_service(env) -> ForecastService:
    return ForecastService(
        env["store"],
        OfflineModel(),
        sentiment_provider=env["sentiment"].forecast_input,
        sentiment_claim_verifier=env["sentiment"].verify_claims,
    )


def test_wheat_forecast_carries_an_estimated_sentiment_line(env):
    service = _wired_service(env)
    forecast = service.run_forecast("wheat", "delhi_khari_baoli")
    line = next(l for l in forecast.lines if l.driver == "sentiment")
    assert line.input_summary["state"] == "estimated"
    assert line.coefficient is not None
    assert line.input_summary["pack_version"] == "2026.10.1"
    assert line.input_summary["cited_item_ids"]
    assert verify_forecast(forecast) == []
    assert "sentiment" in forecast.days[0].contributions
    view = service.sentiment_view(forecast.forecast_id)
    assert view["state"] == "estimated"


@pytest.mark.parametrize(
    "commodity,market", [("groundnut", "rajkot"), ("coffee", "bengaluru")]
)
def test_thin_corpus_commodities_name_sentiment_not_estimable(env, commodity, market):
    service = _wired_service(env)
    forecast = service.run_forecast(commodity, market)
    line = next(l for l in forecast.lines if l.driver == "sentiment")
    assert line.input_summary["state"] == "not_estimable"
    assert line.coefficient is None
    assert line.input_summary["reason"]
    assert all(v == 0.0 for v in line.contribution_path_inr)
    assert "sentiment_not_estimable" in forecast.missing_drivers
    assert forecast.days[0].contributions["sentiment"] == 0.0
    assert verify_forecast(forecast) == []


def test_rich_commodities_are_all_estimable(env):
    service = _wired_service(env)
    for commodity, market in (
        ("soybean", "indore"),
        ("basmati_rice", "delhi_khari_baoli"),
        ("chili", "guntur"),
        ("cumin", "unjha"),
    ):
        forecast = service.run_forecast(commodity, market)
        line = next(l for l in forecast.lines if l.driver == "sentiment")
        assert line.input_summary["state"] == "estimated", commodity
        assert verify_forecast(forecast) == [], commodity


def test_forecast_without_sentiment_input_is_unchanged(tmp_path):
    db = str(tmp_path / "plain.db")
    store = build_store(db)
    truth = build_truth_store(db)
    load_dataset(store, truth, SEED)
    service = ForecastService(store, OfflineModel())
    forecast = service.run_forecast("wheat", "delhi_khari_baoli")
    assert all(l.driver != "sentiment" for l in forecast.lines)
    assert "sentiment" not in forecast.days[0].contributions
    assert "sentiment_not_estimable" not in forecast.missing_drivers
    assert verify_forecast(forecast) == []
    assert service.sentiment_view(forecast.forecast_id)["state"] == "absent"


# --- commentary claims ---------------------------------------------------------


def test_offline_commentary_cites_its_sentiment_reading(env):
    service = _wired_service(env)
    forecast = service.run_forecast("wheat", "kanpur")
    commentary = service.draft_commentary(forecast.forecast_id)
    assert "Sentiment reading (direction per cited items)" in commentary.text
    line = next(l for l in forecast.lines if l.driver == "sentiment")
    for item_id in line.input_summary["cited_item_ids"]:
        assert item_id in commentary.text


class _UncitedClaimModel(OfflineModel):
    profile_name = "uncited"

    def draft_commentary(self, *, subject, figures):
        return f"{subject}. Market sentiment reads supportive this month."


class _UnclassifiedCitationModel(OfflineModel):
    profile_name = "unclassified-citation"
    bad_item_id = ""

    def draft_commentary(self, *, subject, figures):
        return (
            f"{subject}. Sentiment reading (direction per cited items): "
            f"supportive — items {self.bad_item_id}."
        )


def test_uncited_sentiment_claim_is_refused(env):
    service = ForecastService(
        env["store"],
        _UncitedClaimModel(),
        sentiment_provider=env["sentiment"].forecast_input,
        sentiment_claim_verifier=env["sentiment"].verify_claims,
    )
    forecast = service.run_forecast("soybean", "nagpur")
    with pytest.raises(CommentaryVerificationError):
        service.draft_commentary(forecast.forecast_id)


def test_wrong_direction_claim_is_refused(env):
    sentiment = env["sentiment"]
    line_forecast = _wired_service(env).run_forecast("chili", "warangal")
    line = next(l for l in line_forecast.lines if l.driver == "sentiment")
    cited = ", ".join(line.input_summary["cited_item_ids"])
    wrong_word = (
        "supportive" if line.input_summary["latest_index_value"] < 0 else "headwind"
    )

    class WrongDirectionModel(OfflineModel):
        profile_name = "wrong-direction"

        def draft_commentary(self, *, subject, figures):
            return (
                f"{subject}. Sentiment reading (direction per cited items): "
                f"{wrong_word} — items {cited}."
            )

    service = ForecastService(
        env["store"],
        WrongDirectionModel(),
        sentiment_provider=sentiment.forecast_input,
        sentiment_claim_verifier=sentiment.verify_claims,
    )
    forecast = service.run_forecast("chili", "warangal")
    with pytest.raises(CommentaryVerificationError):
        service.draft_commentary(forecast.forecast_id)


def test_claim_citing_an_unclassified_item_is_refused(env):
    unclassified = next(
        e for e in env["sentiment"].list_extractions("cumin") if e.status == "unclassified"
    )
    model = _UnclassifiedCitationModel()
    model.bad_item_id = unclassified.item_id
    service = ForecastService(
        env["store"],
        model,
        sentiment_provider=env["sentiment"].forecast_input,
        sentiment_claim_verifier=env["sentiment"].verify_claims,
    )
    forecast = service.run_forecast("cumin", "jodhpur")
    with pytest.raises(CommentaryVerificationError):
        service.draft_commentary(forecast.forecast_id)


# --- the API surface ------------------------------------------------------------


def test_api_sentiment_surface(env):
    client = TestClient(create_app(env["store"]))
    r = client.get("/sentiment/manifest")
    assert r.status_code == 200 and r.json()["item_count"] == 583

    r = client.get("/sentiment/items", params={"commodity": "coffee"})
    assert r.status_code == 200 and len(r.json()["items"]) == 4

    r = client.get("/sentiment/items", params={"commodity": "wheat"})
    item_id = r.json()["items"][0]["item_id"]
    r = client.get(f"/sentiment/items/{item_id}")
    assert r.status_code == 200
    assert r.json()["item"]["item_id"] == item_id
    assert r.json()["extraction"]["item_id"] == item_id

    r = client.get("/sentiment/extractions", params={"commodity": "coffee"})
    assert r.status_code == 200 and len(r.json()["extractions"]) == 4

    r = client.get("/sentiment/index/wheat")
    assert r.status_code == 200 and len(r.json()["indices"]) > 100
    week = r.json()["indices"][0]["week_start"]
    r = client.get(f"/sentiment/index/wheat/{week}")
    assert r.status_code == 200 and r.json()["week_start"] == week
    r = client.get("/sentiment/index/coffee/2026-02-02")
    assert r.status_code == 404  # absent, never zero-filled

    r = client.get("/sentiment/verify")
    assert r.status_code == 200 and r.json()["problems"] == []

    r = client.post("/sentiment/run")
    assert r.status_code == 200 and r.json()["extractions_new"] == 0

    service = _wired_service(env)
    forecast = service.run_forecast("wheat", "indore")
    r = client.get(f"/forecasts/{forecast.forecast_id}/sentiment")
    assert r.status_code == 200 and r.json()["state"] == "estimated"
    assert r.json()["line"]["driver"] == "sentiment"


# --- isolation: the scoring path never sees the planted intent ------------------

_SCORING_MODULES = ("pack.py", "extract.py", "index.py", "verify.py", "service.py", "models.py")


def test_scoring_modules_never_touch_the_intent():
    package = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "fmcg_forecast"
        / "sentiment"
    )
    for name in _SCORING_MODULES:
        path = package / name
        text = path.read_text(encoding="utf-8")
        assert "sentiment_intent" not in text, name
        tree = ast.parse(text)
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for imported in names:
                assert not imported.endswith(".corpus"), (name, imported)
                assert not imported.endswith(".grading"), (name, imported)
                assert imported != "corpus" and imported != "grading", (name, imported)


def test_migration_0004_creates_the_sentiment_tables(env):
    conn = sqlite3.connect(env["db"])
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    conn.close()
    assert {
        "sentiment_items",
        "sentiment_extractions",
        "sentiment_indices",
        "sentiment_corpus_manifest",
        "sentiment_intent",
    } <= tables
    migrations = (
        Path(__file__).resolve().parents[1] / "migrations"
    )
    assert (migrations / "sqlite" / "0004_sentiment.sql").exists()
    assert (migrations / "postgres" / "0004_sentiment.sql").exists()
