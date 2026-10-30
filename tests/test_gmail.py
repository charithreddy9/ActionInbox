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


def test_html_only_message_contains_visible_charge_and_not_markup():
    html=('<!doctype html><html><head><style>div {color:red}</style></head>'
          '<body><div>As a reminder, your Gold free trial ends tomorrow. '
          'You’ll be charged $5/month to your brokerage account when your free trial ends.</div>'
          '<table><tr><td>Other content</td></tr></table></body></html>')
    parsed=gmail.extract_body({"mimeType":"text/html","body":{"data":b64(html)}})
    assert "Gold free trial ends tomorrow" in parsed
    assert "$5/month" in parsed
    assert "<html" not in parsed
    assert "{color:red}" not in parsed


def test_mislabelled_html_plain_body_is_cleaned():
    html='<!doctype html><html><body><div>Your Gold free trial ends tomorrow.</div></body></html>'
    parsed=gmail.extract_body({"mimeType":"text/plain","body":{"data":b64(html)}})
    assert "trial ends tomorrow" in parsed
    assert "<div" not in parsed


def test_sent_date_is_not_todays_date():
    assert gmail._date_from_header("Thu, 29 Oct 2026 21:42:46 -0700")=="2026-10-29"
    assert gmail._date_from_header("invalid date") is None


def test_gmail_message_exposes_reference_date(monkeypatch):
    class Req:
        def execute(self):
            return {"payload":{"mimeType":"text/html","headers":[
                {"name":"Subject","value":"Your free trial is ending"},
                {"name":"Date","value":"Thu, 29 Oct 2026 20:00:00 -0400"}],
                "body":{"data":b64("<html><body>Trial ends tomorrow.</body></html>")}}}
    class Msg:
        def get(self,**kw):return Req()
    class Users:
        def messages(self):return Msg()
    class Service:
        def users(self):return Users()
    monkeypatch.setattr(gmail,"_service",lambda:Service())
    result=TestClient(api.app).get("/api/gmail/messages/abcdef0123456789").json()
    assert result["reference_date"]=="2026-10-29"
    assert "Trial ends tomorrow." in result["body"]
    assert "<html" not in result["body"]


def test_repeated_html_sections_only_appear_once():
    msg="As a reminder, your Gold free trial ends tomorrow."
    html=f'<html><body><div>{msg}</div><div>{msg}</div></body></html>'
    result=gmail.extract_body({"mimeType":"text/html","body":{"data":b64(html)}})
    assert result.count("Gold free trial ends tomorrow")==1


def test_repeated_multipart_plain_bodies_are_deduplicated():
    text="As a reminder, your Gold free trial ends tomorrow."
    payload={"mimeType":"multipart/mixed","parts":[
       {"mimeType":"text/plain","body":{"data":b64(text)}},
       {"mimeType":"text/plain","body":{"data":b64(text)}}]}
    assert gmail.extract_body(payload)==text
