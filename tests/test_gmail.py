"""Mock-only integration tests; no OAuth account or Gmail API credentials required."""
import base64
from fastapi.testclient import TestClient
from backend import gmail,app as api

def b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode()

def test_readonly_permission():
    assert gmail.SCOPES == ["https://www.googleapis.com/auth/gmail.readonly"]

def test_unconfigured_is_safe(tmp_path,monkeypatch):
    monkeypatch.setattr(gmail,"CLIENT_FILE",tmp_path/"absent")
    monkeypatch.setattr(gmail,"TOKEN_FILE",tmp_path/"absent")
    client=TestClient(api.app)
    assert client.get("/api/gmail/status").json()["connected"] is False
    assert client.get("/api/gmail/messages").status_code == 503

def test_extract_plain_not_attachment():
    body={"mimeType":"multipart/mixed","parts":[
        {"mimeType":"text/plain","body":{"data":b64("Please reply tomorrow.")}},
        {"mimeType":"text/plain","filename":"secret.txt","body":{"data":b64("secret")}}]}
    assert gmail.extract_body(body)=="Please reply tomorrow."

def test_metadata_before_message_body(monkeypatch):
    calls=[]
    class Req:
        def __init__(self,kw):self.kw=kw
        def execute(self):
            calls.append(self.kw)
            if "q" in self.kw:return {"messages":[{"id":"abcdef0123456789"}]}
            if self.kw["format"]=="metadata":return {"payload":{"headers":[{"name":"Subject","value":"Hello"}]}}
            return {"payload":{"headers":[],"mimeType":"text/plain","body":{"data":b64("Please send the form.")}}}
    class Msg:
        def list(self,**kw):return Req(kw)
        def get(self,**kw):return Req(kw)
    class Users:
        def messages(self):return Msg()
    class Service:
        def users(self):return Users()
    monkeypatch.setattr(gmail,"_service",lambda:Service())
    client=TestClient(api.app)
    listing=client.get("/api/gmail/messages").json()
    assert listing["messages"][0]["subject"]=="Hello"
    assert "body" not in listing["messages"][0]
    assert [c.get("format") for c in calls if "format" in c]==["metadata"]
    result=client.get("/api/gmail/messages/abcdef0123456789").json()
    assert "Please send" in result["body"]
    assert [c.get("format") for c in calls if "format" in c]==["metadata","full"]
