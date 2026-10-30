"""Synthetic benchmark runner tests. No Gmail access, Ollama or paid APIs."""
import json
from pathlib import Path

from backend import evaluate_local_ai
from backend.local_ai import LocalAIUnavailable


def fixture():
    return json.loads(evaluate_local_ai.DATASET.read_text(encoding="utf-8"))["cases"]


def proposal(email, title="Review request", evidence=None, due_date=None, source_ids=None):
    return {
        "title": title,
        "source_excerpt": evidence or email["body"],
        "due_date": due_date,
        "source_ids": source_ids or [email["id"]],
    }


def test_fictional_cases_have_unique_ids_and_valid_anchors():
    cases = fixture()
    assert len(cases) >= 15
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert 1 <= len(case["emails"]) <= 5
        ids = {m["id"] for m in case["emails"]}
        assert len(ids) == len(case["emails"])
        for gold in case["expected"]:
            assert set(gold["source_ids"]).issubset(ids)
            assert any(
                gold["anchor"].casefold() in msg["body"].casefold()
                for msg in case["emails"]
            )


def test_scoring_exact_match_and_false_positives():
    case = fixture()[0]
    gold = case["expected"][0]
    row = proposal(
        case["emails"][0],
        evidence=case["emails"][0]["body"],
        due_date=gold["due_date"],
    )
    score = evaluate_local_ai.score_one([row], [gold])
    assert score["true_positives"] == 1
    assert score["false_positives"] == 0
    assert score["task_count_correct"]


def test_wrong_date_and_missing_source_do_not_get_credit():
    case = fixture()[0]
    gold = case["expected"][0]
    row = proposal(case["emails"][0], due_date="2026-11-09")
    result = evaluate_local_ai.score_one([row], [gold])
    assert result["true_positives"] == 0
    assert result["false_positives"] == 1
    assert result["false_negatives"] == 1
    wrong_source = proposal(case["emails"][0], due_date=gold["due_date"],
                            source_ids=["other"])
    assert evaluate_local_ai.score_one([wrong_source], [gold])["true_positives"] == 0


def test_fictional_suite_mock_analyzer_does_not_claim_real_accuracy():
    cases = fixture()
    def fake(emails):
        return {"suggestions": [], "discarded_unsupported": 0}
    result = evaluate_local_ai.evaluate(cases, analyze=fake, model="fake")
    assert result["case_count"] == len(cases)
    assert result["predicted_tasks"] == 0
    assert result["expected_tasks"] > 0
    assert result["strict_evidence_date_source_recall"] == 0
    assert "fictional" in result["dataset_type"]


def test_runner_records_timeout_failure_and_does_not_silence_it():
    def unavailable(emails):
        raise LocalAIUnavailable("Simulated offline Ollama")
    result = evaluate_local_ai.evaluate(fixture()[:1], analyze=unavailable)
    assert result["cases_with_errors"] == 1
    assert result["results"][0]["error"] == "Simulated offline Ollama"
    assert result["task_count_accuracy"] == 0


def test_nonactionable_fixture_is_not_rewarded_as_task():
    case = next(c for c in fixture() if c["id"] == "marketing_trial_offer")
    assert case["expected"] == []
    result = evaluate_local_ai.score_one([], case["expected"])
    assert result["task_count_correct"]
    assert result["expected"] == 0
