# ActionInbox v5 — Recruiter demo and local-model evaluation

**Status:** development prototype. The local model uses Ollama and Qwen3 4B. The project's GitHub Actions tests **mock** local model replies; they do not prove Qwen's real task extraction accuracy. A previous local test returned HTTP 503; the exact cause requires testing on the host laptop.

## Three-minute demo using only fictional emails

1. Open **ActionInbox** at `http://127.0.0.1:5173`. Show the local-first privacy design and current task board.
2. Open **Gmail (optional)** and explain that OAuth is read-only; do **not** display personal email content while recording. You may demonstrate Gmail with a dedicated synthetic test mailbox, or use the **local text API** below without Gmail.
3. Use this **fictional** email:

   **Subject:** Project deadlines

   > Please pay the lab invoice by November 5, 2026. Upload the signed project report by November 8, 2026. The appointment from October 20 has already been cancelled.

4. Demonstrate one local LLM inference with the API below. Show the model's task suggestions, source quotations and proposed due dates. **Do not claim the model must find exactly two tasks unless the output actually does.**
5. In the browser, use the Gmail selector only with a dedicated fictional/test account if you want to show the editable approval UI. Otherwise, show the existing review-first task interface with its fictional default example.
6. Explain that **only approved tasks** enter local SQLite and that no email is sent or modified. Don't expose actual emails, reference numbers, access tokens, or identifying data.

### Local-only inference smoke test (no Gmail)

After installing Ollama and downloading the model:

```powershell
ollama pull qwen3:4b
cd C:\Users\ysaic\ActionInbox
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

Open a second PowerShell window:

```powershell
$body = @{
  subject = "Project deadlines"
  text = "Please pay the lab invoice by November 5, 2026. Upload the signed project report by November 8, 2026. The appointment from October 20 has already been cancelled."
  reference_date = "2026-10-30"
} | ConvertTo-Json

try {
  Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/ai/text" -Method POST -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 6
} catch {
  $_.ErrorDetails.Message
}
```

**Interpretation:** A successful HTTP response establishes that the local model endpoint ran; it **does not** prove the model's task count, dates, or evidence are correct. Inspect all returned fields.

### Reproducible fictional-email evaluation

From the project root:

```powershell
# Shortest local smoke test: one project-authored fictional case
.\.venv\Scripts\python.exe -m backend.evaluate_local_ai --case single_document

# Full development suite: 18 fictional cases, one Ollama invocation per case
.\.venv\Scripts\python.exe -m backend.evaluate_local_ai
```

Results are written to ignored `data/local-ai-evaluation.json` unless `--report` chooses a different path. Raw personal email content and OAuth tokens are never part of the dataset.

**Metrics:**
- **Task-count accuracy:** fraction of cases with the correct number of suggested actionable tasks.
- **Strict precision/recall/F1:** a predicted task must quote the expected evidence anchor, match its ISO due date, and cite the exact source message IDs to count.
- **Latency:** wall-clock seconds per case, summarized using median latency.
- **Failure cases:** malformed output and Ollama runtime errors are kept visible in the report.

**Limitations:** Dataset is project-authored and tiny, and scoring is intentionally rigid. A legitimate alternative evidence quote can be marked wrong. Zero-task emails do not contribute conventional true negatives to precision/recall. Metrics must not be compared to the earlier **77.8% intent-category** classifier score, which evaluated a different task. No verified real-Qwen performance results are claimed here.

### A screenshot checklist for a public GitHub/LinkedIn demo

- Redact or avoid **all** real sender addresses, message bodies, tracking references and billing information.
- Show the local model name, explicit review controls, and one or two real **fictional-example** results.
- Show corrected dates/evidence where applicable; demonstrate limitations rather than hiding failures.
- Show the benchmark commands and a real report **only after running it**.
- Keep all OAuth secrets, token files and raw mail out of your repository.

## Next milestones

1. Diagnose local Ollama HTTP failures with the fictional text smoke test.
2. Collect real-Qwen measurements on the 18-case fictional set and fix format/timeouts if needed.
3. Add a genuinely independent, privacy-safe evaluation set; measure task counts and incorrect grouping.
4. Implement easy Gmail account switching with explicit account-scoped task isolation.
5. Release v5 after verified accuracy and end-to-end review/save tests.
