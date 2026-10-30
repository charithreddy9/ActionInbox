"""Reproducible, fictional-email evaluation for the local Qwen/Ollama pipeline.

This is a project-authored development set, NOT an independent accuracy benchmark.
No real Gmail emails or OAuth credentials are involved.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time

from .local_ai import EmailItem, LocalAIUnavailable, analyze_emails

DATASET = Path(__file__).resolve().parents[1] / "research" / "local_ai_fictional_cases.json"
DEFAULT_REPORT = Path(__file__).resolve().parents[1] / "data" / "local-ai-evaluation.json"


def _match(predicted: dict, expected: dict) -> bool:
    """Match task-specific source evidence, source IDs and deadline.

    This is intentionally strict: alternate valid paraphrases count as errors.
    A source quote must contain the expected anchor; merely mentioning a
    related topic in the task title is insufficient.
    """
    quote = " ".join(predicted["source_excerpt"].casefold().split())
    anchor = " ".join(expected["anchor"].casefold().split())
    return (
        anchor in quote
        and predicted["due_date"] == expected["due_date"]
        and set(predicted.get("source_ids", [])) == set(expected["source_ids"])
    )


def score_one(suggestions: list[dict], expected: list[dict]) -> dict:
    used = set()
    true_positives = 0
    for gold in expected:
        for index, candidate in enumerate(suggestions):
            if index not in used and _match(candidate, gold):
                used.add(index)
                true_positives += 1
                break
    return {
        "expected": len(expected),
        "predicted": len(suggestions),
        "true_positives": true_positives,
        "false_positives": len(suggestions) - true_positives,
        "false_negatives": len(expected) - true_positives,
        "task_count_correct": len(suggestions) == len(expected),
    }


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def evaluate(cases: list[dict], analyze=analyze_emails, model="configured local model") -> dict:
    results = []
    for case in cases:
        emails = [EmailItem(**email) for email in case["emails"]]
        started = time.perf_counter()
        try:
            result = analyze(emails)
            elapsed = round(time.perf_counter() - started, 3)
            metrics = score_one(result["suggestions"], case["expected"])
            metrics.update({
                "case_id": case["id"],
                "description": case["description"],
                "elapsed_seconds": elapsed,
                "unsupported_rejected": result.get("discarded_unsupported", 0),
                "error": None,
            })
        except (LocalAIUnavailable, ValueError) as exc:
            elapsed = round(time.perf_counter() - started, 3)
            metrics = {
                "case_id": case["id"],
                "description": case["description"],
                "expected": len(case["expected"]), "predicted": 0,
                "true_positives": 0, "false_positives": 0,
                "false_negatives": len(case["expected"]),
                "task_count_correct": False, "elapsed_seconds": elapsed,
                "unsupported_rejected": 0, "error": str(exc),
            }
        results.append(metrics)

    tp = sum(r["true_positives"] for r in results)
    fp = sum(r["false_positives"] for r in results)
    fn = sum(r["false_negatives"] for r in results)
    precision = _rate(tp, tp + fp)
    recall = _rate(tp, tp + fn)
    f1 = (round(2 * precision * recall / (precision + recall), 4)
          if precision is not None and recall is not None and precision + recall else None)
    return {
        "dataset_type": "project-authored fictional development set; not independently validated",
        "model": model, "utc_generated": datetime.now(timezone.utc).isoformat(),
        "case_count": len(results), "cases_with_errors": sum(bool(r["error"]) for r in results),
        "expected_tasks": sum(r["expected"] for r in results),
        "predicted_tasks": sum(r["predicted"] for r in results),
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "strict_evidence_date_source_precision": precision,
        "strict_evidence_date_source_recall": recall,
        "strict_evidence_date_source_f1": f1,
        "task_count_accuracy": _rate(sum(r["task_count_correct"] for r in results), len(results)),
        "median_case_seconds": round(statistics.median(r["elapsed_seconds"] for r in results), 3)
                               if results else None,
        "results": results,
        "limitations": [
            "All examples are fictional and authored for development.",
            "The matcher demands a literal evidence anchor, correct source group, and exact date.",
            "Valid paraphrased evidence or an alternate legitimate action can be counted wrong.",
            "A 0-task case contributes no true negatives to precision/recall.",
            "Runtime errors remain visible and count against task-count accuracy.",
            "Do not compare these metrics with the older 27-item intent-category study.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate ActionInbox local LLM on fictional emails")
    parser.add_argument("--case", default=None, help="Single case ID for a quick smoke test")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    cases = dataset["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            parser.error("Unknown case ID")
    report = evaluate(cases)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Evaluated {report['case_count']} fictional cases; "
          f"expected {report['expected_tasks']}, predicted {report['predicted_tasks']}, "
          f"matched {report['true_positives']}, errors {report['cases_with_errors']}")
    print(f"Precision={report['strict_evidence_date_source_precision']} "
          f"Recall={report['strict_evidence_date_source_recall']} "
          f"Task-count accuracy={report['task_count_accuracy']}")
    print(f"Local report: {args.report}")
    if report["cases_with_errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
