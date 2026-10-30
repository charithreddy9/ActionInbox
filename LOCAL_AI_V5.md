# ActionInbox v5 — Local Model Email Intelligence

**Development branch:** `feature/llm-email-intelligence`. The v4 rule-based radar is preserved. v5 adds a separate **Local AI** panel under Gmail.

## What is implemented
- Select **1–5 messages** from Gmail's manually searched metadata list.
- Read selected bodies through the existing **read-only Gmail API** and send them to a local Ollama model, **not a hosted AI API**.
- Model reasons over full message context and returns **zero, one or multiple distinct action suggestions**, free-form categories, dates, statuses, evidence and source IDs.
- One model pass can group related selected emails (requires model correctness; output is reviewed).
- Server validates schema, IDs, categories, ISO dates, and **verbatim evidence**; rejects unsupported claims where possible.
- Review, edit and explicitly approve suggestions; approved records go to existing SQLite task board. Scans and draft suggestions do **not** persist.
- Repeated analysis of identical selected message sets produces stable IDs; SQLite's primary key blocks identical approvals.

**Current limitations:** Real semantic accuracy is model-dependent and not yet benchmarked on a representative corpus. Evidence validation ensures the quote exists, not that conclusions are correct or dates were assigned to the right task. The model output is capped at 24 events; tasks beyond that must be flagged for further review. When analyzing related messages, select them **in the same batch**. Identical events across differing selections are not guaranteed deduplicated. Old keyword Radar remains available as a separate manual feature. Email account switching is **not yet implemented**.

## Windows local setup

Install Ollama from the official source: https://ollama.com/download

Open PowerShell:

```powershell
ollama pull qwen3:4b
ollama list
```

Model inference uses **localhost 127.0.0.1:11434** only. To choose a different installed model, set `ACTIONINBOX_OLLAMA_MODEL` before launching FastAPI.

Run your existing backend and frontend:

```powershell
cd C:\Users\ysaic\ActionInbox
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

In another PowerShell:

```powershell
cd C:\Users\ysaic\ActionInbox\frontend
npm run dev
```

Visit http://127.0.0.1:5173 → Gmail (optional) → Choose an email → Find emails. Select checkboxes next to up to five emails, then use **Local AI → Analyze selected emails** and approve only correct suggestions. No Gmail token migration is required.

**Privacy:** Keep `credentials.json` and `data/gmail-token.json` private. Do not expose FastAPI or Ollama outside localhost. The existing OAuth account remains connected. Email text is processed locally, but an installed model's own behavior must still be evaluated; model-generated content is always untrusted until reviewed.

**Roadmap:** Account switching is the subsequent milestone, with explicit disconnect/reconnect and account-scoped tracking to avoid mixing tasks from different Gmail accounts.

## Reproducible model evaluation and recruiter demo

See [DEMO.md](DEMO.md) for a privacy-safe walkthrough and explicit local runtime smoke test. An 18-case **fictional, project-authored** dataset lives in [research/local_ai_fictional_cases.json](research/local_ai_fictional_cases.json). Run `python -m backend.evaluate_local_ai --case single_document` for one case or `python -m backend.evaluate_local_ai` for all cases. These commands require the actual installed local model; CI uses mocked model responses and does not establish inference accuracy.
