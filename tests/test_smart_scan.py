
"""Smart scan resilience using synthetic Gmail responses; never connects to Gmail."""
from backend import gmail

class Request:
    def __init__(self, response=None, error=None):
        self.response=response; self.error=error
    def execute(self):
        if self.error:raise self.error
        return self.response

class GmailMessages:
    def __init__(self, fail_kind=None, fail_message=False):
        self.queries=[]
        self.fail_kind=fail_kind
        self.fail_message=fail_message
    def list(self,**kw):
        self.queries.append(kw["q"])
        if self.fail_kind and self.fail_kind in kw["q"]:return Request(error=RuntimeError("request failed"))
        return Request({"messages":[{"id":"abcdef0123456789"}]})
    def get(self,**kw):
        if self.fail_message:return Request(error=RuntimeError("request failed"))
        return Request({"payload":{"headers":[
          {"name":"Subject","value":"Luggage pickup reminder: 830841167"},
          {"name":"From","value":"LugLess"},
          {"name":"Date","value":"Thu, 29 Oct 2026 13:00:00 -0400"}],
          "mimeType":"text/plain",
          "body":{"data":""}}})

class Service:
    def __init__(self,msg):self.msg=msg
    def users(self):return self
    def messages(self):return self.msg

def test_focused_travel_scan(monkeypatch):
    msg=GmailMessages()
    monkeypatch.setattr(gmail,"_service",lambda:Service(msg))
    result=gmail.scan_smart_inbox(20,"travel")
    assert result["scanned"]==1
    assert result["undated"][0]["type"]=="travel"
    assert len(msg.queries)==1 and "luggage pickup" in msg.queries[0]

def test_broad_scan_uses_ten_per_category(monkeypatch):
    msg=GmailMessages()
    monkeypatch.setattr(gmail,"_service",lambda:Service(msg))
    result=gmail.scan_smart_inbox(20,"all")
    assert result["limit_per_category"]==10
    assert len(msg.queries)==8
    assert result["scanned"]==1

def test_failed_search_produces_partial_results(monkeypatch):
    msg=GmailMessages(fail_kind="luggage pickup")
    monkeypatch.setattr(gmail,"_service",lambda:Service(msg))
    result=gmail.scan_smart_inbox(20,"all")
    assert result["partial"] and result["scanned"]==1
    assert any(x["stage"]=="search" for x in result["errors"])

def test_failed_focused_scan_is_actionable_error(monkeypatch):
    msg=GmailMessages(fail_kind="luggage pickup")
    monkeypatch.setattr(gmail,"_service",lambda:Service(msg))
    try:gmail.scan_smart_inbox(20,"travel")
    except gmail.GmailUnavailable as exc:
        assert "Gmail search failed" in str(exc)
    else:assert False

def test_invalid_scope_rejected():
    try:gmail.scan_smart_inbox(20,"everything")
    except gmail.GmailUnavailable:pass
    else:assert False
