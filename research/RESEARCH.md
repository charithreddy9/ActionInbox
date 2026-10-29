# ActionInbox research notebook

## The questions I'm exploring

How reliably can a lightweight, CPU-only pipeline distinguish an email action item from a status update? How often will an intent classifier mistake a mention of an appointment, bill, or document for an instruction? Which parts of task extraction can be tested independently?

## Current baseline

- 60 synthetic hand-written training sentences (12 examples in each of five intent categories)
- TF-IDF word unigrams/bigrams, scikit-learn logistic regression with fixed random seed
- Extra keyword rules for common payment, meeting, document, and reply patterns
- Text extraction from paste or `.eml` with simple HTML stripping
- Sentence-level action trigger detection and date extraction with explicit patterns
- No hosted model, no inbox integration, and no automatic task creation

## Reported results

The development holdout contains 27 manually written sentences. The classifier predicts 21 categories correctly: **77.8% accuracy**, **macro-F1 0.778**. See [`evaluation.json`](evaluation.json) for the full list of expected and predicted labels and the confusion matrix.

The six failures include misclassified indirect requests and informational sentences. For example, an email saying a bill *was already paid* may still trigger payment keywords. This is why category classification is not the same as deciding whether a task exists, and why the app requires review.

## Scientific limitations

This is **not** a blind experiment. The same author wrote the training and evaluation phrases, and they share a small vocabulary and domain. No results are claimed for real Gmail messages or external corpora. The rule layer and classifier were adjusted during development while inspecting the test cases. The reported number is a development check, not an unbiased estimate. There is no statistical confidence interval, data drift analysis, or deployment A/B test.

The evaluation only measures categories, not sentence detection, due dates, human usefulness, notification accuracy, or end-to-end precision/recall. Unit tests cover selected cases but do not measure broader reliability.

## More meaningful next study

1. Recruit human reviewers to label messages without seeing the system's predictions; split by conversation or sender, not just sentence.
2. Label **action vs. informational** independently from intent categories, due dates, and entity spans.
3. Compare action-only keyword rules, TF-IDF logistic regression, and a CPU-compatible small transformer. Report precision/recall/F1 by category and false tasks per 100 emails.
4. Audit information-leakage risks and adversarial messages. Ensure quoted instructions and forwarded threads are not mistakenly treated as new user requests.
5. Evaluate whether human corrections reduce time spent planning rather than only reporting classification accuracy.

## Reproduce

Run `python -m backend.evaluate` from the repository root. This regenerates `evaluation.json` using the source examples and the same fixed classifier configuration.
