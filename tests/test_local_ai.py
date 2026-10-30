"""Model-driven v5 validation with a fake local model; never uses Gmail or Ollama."""
import json
import pytest
from backend import local_ai

def mail(i="a",text="Please submit documents by November 8, 2026."):
    return local_ai.EmailItem(id=i,subject="Request",body=text,sent_date="2026-10-30")

def fake(events):
    return lambda payload:{"message":{"content":json.dumps({"events":events})}}

def event(**kw):
    base=dict(title="Submit documents",category="paperwork",status="action_needed",
      evidence="Please submit documents by November 8, 2026.",
      source_ids=["a"],due_date="2026-11-08",priority="medium",
      reason="The message requests a submission",event_key="submission")
    base.update(kw)
    return base

def test_multiple_tasks_from_one_email(monkeypatch):
    text="Please submit documents by November 8, 2026. Also book a dentist appointment."
    monkeypatch.setattr(local_ai,"_chat",fake([
      event(),event(title="Book dentist",category="dental_visit",
         evidence="Also book a dentist appointment.",due_date="",event_key="dental")
    ]))
    result=local_ai.analyze_emails([mail(text=text)])
    assert result["task_count"]==2
    assert {x["category"] for x in result["suggestions"]}=={"paperwork","dental_visit"}
    assert result["suggestions"][1]["due_date"] is None

def test_zero_tasks_valid(monkeypatch):
    monkeypatch.setattr(local_ai,"_chat",fake([]))
    assert local_ai.analyze_emails([mail()])["task_count"]==0

def test_unsubstantiated_evidence_is_rejected(monkeypatch):
    monkeypatch.setattr(local_ai,"_chat",fake([event(evidence="Your $5000 payment is overdue immediately.")]))
    result=local_ai.analyze_emails([mail()])
    assert result["task_count"]==0
    assert result["discarded_unsupported"]==1

def test_invalid_date_rejected(monkeypatch):
    monkeypatch.setattr(local_ai,"_chat",fake([event(due_date="2026-02-30")]))
    assert local_ai.analyze_emails([mail()])["task_count"]==0

def test_completed_cancelled_not_saved(monkeypatch):
    monkeypatch.setattr(local_ai,"_chat",fake([
      event(status="completed"),event(status="cancelled",event_key="other")]))
    result=local_ai.analyze_emails([mail()])
    assert result["task_count"]==0
    assert result["non_actionable_events"]==2

def test_related_emails_share_one_event(monkeypatch):
    monkeypatch.setattr(local_ai,"_chat",fake([
      event(title="Check pickup failure",category="luggage_pickup",
        status="action_needed",evidence="Pickup attempt was unsuccessful.",
        source_ids=["a","b"],event_key="pickup:12345",due_date="")
    ]))
    result=local_ai.analyze_emails([
      mail("a","Luggage pickup reminder."),
      mail("b","Pickup attempt was unsuccessful.")
    ])
    assert result["task_count"]==1
    assert result["suggestions"][0]["source_count"]==2

def test_rejects_fake_source_id(monkeypatch):
    monkeypatch.setattr(local_ai,"_chat",fake([event(source_ids=["unknown"])]))
    assert local_ai.analyze_emails([mail()])["task_count"]==0

def test_user_data_not_assigned_category_by_keyword(monkeypatch):
    monkeypatch.setattr(local_ai,"_chat",fake([event(category="model_chosen_value")]))
    assert local_ai.analyze_emails([mail()])["suggestions"][0]["category"]=="model_chosen_value"

def test_max_five_emails():
    with pytest.raises(ValueError):
        local_ai.analyze_emails([mail(str(i)) for i in range(6)])

def test_stable_id_and_duplicate_output_suppressed(monkeypatch):
    monkeypatch.setattr(local_ai,"_chat",fake([event(),event()]))
    first=local_ai.analyze_emails([mail()])
    second=local_ai.analyze_emails([mail()])
    assert first["task_count"]==1 and second["task_count"]==1
    assert first["suggestions"][0]["id"]==second["suggestions"][0]["id"]

def test_invalid_model_json_is_friendly(monkeypatch):
    monkeypatch.setattr(local_ai,"_chat",lambda payload:{"message":{"content":"not json"}})
    with pytest.raises(local_ai.LocalAIUnavailable):
        local_ai.analyze_emails([mail()])


def test_ollama_http_400_has_useful_safe_error(monkeypatch):
    from urllib.error import HTTPError
    from io import BytesIO
    def fail(*args, **kwargs):
        # Upstream response deliberately includes secrets to ensure they aren't echoed.
        raise HTTPError(local_ai.OLLAMA_URL + "/api/chat", 400, "Bad Request",
                        {}, BytesIO(b"private email content"))
    monkeypatch.setattr(local_ai,"urlopen",fail)
    with pytest.raises(local_ai.LocalAIUnavailable, match=r"HTTP 400") as caught:
        local_ai._chat({"model":local_ai.MODEL})
    assert "private email" not in str(caught.value)
    assert "Cannot reach" not in str(caught.value)

def test_ollama_http_500_mentions_inference_not_connection(monkeypatch):
    from urllib.error import HTTPError
    from io import BytesIO
    def fail(*args, **kwargs):
        raise HTTPError(local_ai.OLLAMA_URL + "/api/chat", 500, "error",
                        {}, BytesIO(b"private email content"))
    monkeypatch.setattr(local_ai,"urlopen",fail)
    with pytest.raises(local_ai.LocalAIUnavailable, match=r"inference \(HTTP 500\)"):
        local_ai._chat({"model":local_ai.MODEL})

def test_ollama_connection_error_is_distinct(monkeypatch):
    from urllib.error import URLError
    monkeypatch.setattr(local_ai,"urlopen",lambda *a,**kw: (_ for _ in ()).throw(
        URLError("connection refused")))
    with pytest.raises(local_ai.LocalAIUnavailable, match="Cannot contact Ollama"):
        local_ai._chat({"model":local_ai.MODEL})

def test_ollama_timeout_is_not_reported_as_missing_model(monkeypatch):
    monkeypatch.setattr(local_ai,"urlopen",lambda *a,**kw: (_ for _ in ()).throw(
        TimeoutError("timed out")))
    with pytest.raises(local_ai.LocalAIUnavailable, match="timed out"):
        local_ai._chat({"model":local_ai.MODEL})

def test_ollama_response_data_is_returned(monkeypatch):
    from io import BytesIO
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return b'{"message":{"content":"{}"}}'
    monkeypatch.setattr(local_ai,"urlopen",lambda *a,**kw:Response())
    assert local_ai._chat({"model":local_ai.MODEL})["message"]["content"]=="{}"
