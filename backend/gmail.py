"""Optional, user-initiated Gmail READ-ONLY access for a localhost-only app.

OAuth setup happens in a separate local CLI, never as a browser-triggered API action.
No email bodies or OAuth tokens are stored in ActionInbox's tasks database.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CLIENT_FILE = Path(os.environ.get("ACTIONINBOX_GMAIL_CLIENT", str(ROOT / "credentials.json")))
TOKEN_FILE = Path(os.environ.get("ACTIONINBOX_GMAIL_TOKEN", str(ROOT / "data" / "gmail-token.json")))
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
MAX_BODY = 32000


class GmailUnavailable(RuntimeError):
    """Safe-to-display setup / Gmail connectivity error."""


def connection_status() -> dict:
    return {
        "configured": CLIENT_FILE.is_file(),
        "connected": TOKEN_FILE.is_file(),
        "permission": "gmail.readonly",
        "automatic_sync": False,
        "message_storage": False,
    }


def _save_token(credentials):
    """Keep OAuth credentials in an ignored, user-local file, never the repository."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = TOKEN_FILE.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(credentials.to_json())
        os.replace(temporary, TOKEN_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def _load_credentials():
    if not TOKEN_FILE.is_file():
        raise GmailUnavailable("Gmail is not connected yet. See GMAIL_SETUP.md for the one-time setup.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise GmailUnavailable("Install the optional Google libraries: pip install -r requirements-gmail.txt") from exc
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_token(creds)
        if not creds.valid:
            raise GmailUnavailable("Gmail authorization expired. Run python -m backend.gmail connect again.")
        return creds
    except GmailUnavailable:
        raise
    except Exception as exc:
        raise GmailUnavailable("Gmail authorization needs to be renewed. Run python -m backend.gmail connect.") from exc


def _service():
    creds = _load_credentials()
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GmailUnavailable("Install the optional Google libraries: pip install -r requirements-gmail.txt") from exc
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(payload, name):
    for h in payload.get("headers", []):
        if h.get("name", "").casefold() == name.casefold():
            return str(h.get("value", ""))[:180]
    return ""


class _HTMLText(HTMLParser):
    """Extract visible text from untrusted HTML without rendering it."""
    BLOCKS = {"p", "div", "br", "li", "tr", "td", "h1", "h2", "h3", "h4", "section"}
    SKIP = {"head", "style", "script", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.words = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif self.skip == 0 and tag in self.BLOCKS:
            self.words.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif self.skip == 0 and tag in self.BLOCKS:
            self.words.append("\n")

    def handle_data(self, data):
        if self.skip == 0:
            self.words.append(data)

    def text(self):
        clean = "\n".join(
            " ".join(line.split()) for line in "".join(self.words).splitlines()
            if line.strip()
        )
        return clean


def _looks_like_html(raw):
    # Some Gmail MIME bodies are labelled text/plain yet contain full HTML.
    return bool(re.search(
        r"^\s*(?:<!doctype\s+html\b|<html\b|<head\b|<body\b|<table\b|<div\b)",
        raw[:400], re.I,
    ) and re.search(r"</(?:html|body|table|div)>", raw, re.I))


def _visible_html(raw):
    parser = _HTMLText()
    parser.feed(raw)
    return parser.text()


def _decode(data):
    if not isinstance(data, str) or not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise GmailUnavailable("The selected Gmail message contains invalid text encoding.") from exc


def _dedupe_email_body(text):
    """Collapse duplicate HTML/plain sections while preserving first occurrence."""
    seen = set()
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"[\u200b-\u200f\u2060\ufeff\u00ad]", "", raw)
        line = " ".join(line.split()).strip()
        if not line:
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return "\n".join(lines)


def extract_body(payload):
    """Prefer text/plain, use stripped HTML as fallback. Never fetch attachments."""
    plain, html = [], []

    def walk(part):
        if part.get("filename") or part.get("body", {}).get("attachmentId"):
            return
        content_type = part.get("mimeType", "")
        if content_type.startswith("multipart/"):
            for child in part.get("parts", []):
                walk(child)
            return
        raw = _decode(part.get("body", {}).get("data", ""))
        if content_type == "text/html" or _looks_like_html(raw):
            html.append(_visible_html(raw))
        elif content_type == "text/plain" or (not content_type and raw):
            plain.append(raw)
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    body = "\n".join(plain).strip() or "\n".join(html).strip()
    return _dedupe_email_body(body)[:MAX_BODY]


def _validate_id(message_id):
    # Gmail message IDs are opaque hex-like identifiers; never allow path injection.
    if not re.fullmatch(r"[a-zA-Z0-9]{8,32}", message_id):
        raise GmailUnavailable("Invalid Gmail message ID.")
    return message_id


def list_messages(query="in:inbox newer_than:14d", limit=10):
    if not 1 <= limit <= 10:
        raise GmailUnavailable("Choose between 1 and 10 messages.")
    if len(query) > 120:
        raise GmailUnavailable("Gmail search query is too long.")
    try:
        service = _service()
        response = service.users().messages().list(userId="me", q=query or "in:inbox", maxResults=limit, includeSpamTrash=False).execute()
        # Metadata only: body content is fetched *only* after the user picks a message.
        previews = []
        for entry in response.get("messages", []):
            message_id = _validate_id(entry["id"])
            detail = service.users().messages().get(userId="me", id=message_id,
                format="metadata", metadataHeaders=["Subject", "From", "Date"]).execute()
            headers = detail.get("payload") or {}
            previews.append({"id": message_id,
                "subject": _header(headers, "Subject") or "(No subject)",
                "sender": _header(headers, "From"),
                "date": _header(headers, "Date")})
        return {"messages": previews, "count": len(previews)}
    except GmailUnavailable:
        raise
    except Exception as exc:
        raise GmailUnavailable("Couldn't list Gmail messages. Check your connection and Gmail API setup.") from exc


def _date_from_header(header):
    """Interpret 'tomorrow' relative to when the sender wrote the email."""
    if not header:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(header).date().isoformat()
    except (ValueError, TypeError, OverflowError, IndexError):
        return None


def get_message(message_id):
    message_id = _validate_id(message_id)
    try:
        service = _service()
        message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        payload = message.get("payload") or {}
        body = extract_body(payload)
        return {
            "id": message_id,
            "subject": _header(payload, "Subject") or "(No subject)",
            "sender": _header(payload, "From"),
            "date": _header(payload, "Date"),
            "reference_date": _date_from_header(_header(payload, "Date")),
            "body": body,
            "has_text": bool(body.strip()),
            "not_saved": True,
        }
    except GmailUnavailable:
        raise
    except Exception as exc:
        raise GmailUnavailable("Couldn't read the selected Gmail message. Please retry.") from exc


def connect():
    if not CLIENT_FILE.is_file():
        raise GmailUnavailable("Download a Desktop OAuth client JSON to credentials.json. See GMAIL_SETUP.md.")
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise GmailUnavailable("Install Gmail dependencies with pip install -r requirements-gmail.txt") from exc
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
        # Explicit, interactive loopback flow. No server-side button can initiate this.
        creds = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True, prompt="consent")
        _save_token(creds)
    except Exception as exc:
        raise GmailUnavailable("Google OAuth did not finish. Check your test-user setup and try again.") from exc
    print("Gmail connected locally with read-only permission. Return to ActionInbox and refresh Gmail status.")


def main():
    cli = argparse.ArgumentParser(description="Optional local Gmail connection for ActionInbox")
    cli.add_argument("command", choices=("connect", "status", "disconnect"))
    args = cli.parse_args()
    try:
        if args.command == "connect":
            connect()
        elif args.command == "status":
            print(json.dumps(connection_status(), indent=2))
        else:
            TOKEN_FILE.unlink(missing_ok=True)
            print("Local Gmail token deleted. Revoke ActionInbox's access in your Google Account separately if desired.")
    except GmailUnavailable as exc:
        cli.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()

def scan_deadlines(limit=20):
    """User-triggered bounded scans; nothing persisted."""
    from .deadlines import deadline_hints, sort_items, LIMIT, notice_kind
    if not 1 <= limit <= LIMIT:raise GmailUnavailable("Scan limit must be between 1 and 25.")
    queries={
      "payment":'newer_than:180d {invoice "payment due" "bill due" "amount due" "statement ready" billing}',
      "subscription":'newer_than:180d {subscription renewal renews membership "auto renew"}',
      "trial":'newer_than:180d {"trial ends" "trial expires" "free trial" "trial ending"}',
    }
    try:
        service=_service()
        ids=[];groups={}
        for kind,query in queries.items():
            response=service.users().messages().list(userId="me",q=query,maxResults=limit,includeSpamTrash=False).execute()
            new=[_validate_id(x["id"]) for x in response.get("messages",[])]
            groups[kind]=len(new);ids.extend(new)
        ids=list(dict.fromkeys(ids))[:limit*3]
        matches=[];undated=[]
        for message_id in ids:
            msg=service.users().messages().get(userId="me",id=message_id,format="full").execute()
            payload=msg.get("payload") or {}
            subject=_header(payload,"Subject") or "(No subject)"
            sender=_header(payload,"From");sent_date=_header(payload,"Date")
            body=extract_body(payload)
            hints=deadline_hints(subject,body,sent_date)
            for hint in hints:matches.append({"message_id":message_id,"subject":subject,"sender":sender,**hint})
            if not hints:
                kind=notice_kind(subject,body)
                if kind:undated.append({"message_id":message_id,"subject":subject,"sender":sender,"type":kind})
        return {"items":sort_items(matches),"undated":undated[:30],"scanned":len(ids),"searched_categories":groups,
            "saved":False,"notice":"Possible deadlines only. Review original billing accounts; this is not an exhaustive audit."}
    except GmailUnavailable:raise
    except Exception as exc:raise GmailUnavailable("Deadline scan failed. Check your Gmail connection.") from exc

def _gmail_error_code(exc):
    """Safe diagnostic only: never expose Gmail response bodies or credentials."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    return f"HTTP {status}" if isinstance(status, int) else type(exc).__name__


def _execute_gmail_request(make_request):
    """Retry temporary Google API throttling without logging mailbox content."""
    import time
    for attempt in range(3):
        try:
            return make_request().execute()
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep((attempt + 1) * 0.75)
                continue
            raise


SMART_QUERIES = {
    "payment": 'newer_than:180d {invoice "payment due" "bill due" "amount due" billing}',
    "subscription": 'newer_than:180d {subscription renewal renews "auto renew"}',
    "trial": 'newer_than:180d {"trial ends" "trial expires" "free trial" "trial ending"}',
    "travel": 'newer_than:90d {"pickup reminder" "luggage pickup" "baggage pickup" "drop off" lugless}',
    "flight": 'newer_than:90d {"flight check-in" "boarding pass" "flight reminder" "departure reminder"}',
    "appointment": 'newer_than:90d {"appointment reminder" "appointment confirmed" "meeting reminder" "interview scheduled"}',
    "delivery": 'newer_than:90d {"ready for pickup" "pick up your package" "collect your package" "locker expires"}',
    "document": 'newer_than:90d {"submission deadline" "submit by" "upload your document" "application deadline"}',
}


def scan_smart_inbox(limit=20, category="all"):
    """Explicit, bounded Gmail search. A single failing request does not erase results.

    All-category scans cap each category at 10 messages to avoid rapid API bursts.
    A focused category scan can examine up to 25 matching messages.
    """
    from .deadlines import deadline_hints, notice_kind, sort_items
    from .reminders import reminder_hints
    import time

    if not 1 <= limit <= 25:
        raise GmailUnavailable("Choose a scan limit between 1 and 25.")
    if category != "all" and category not in SMART_QUERIES:
        raise GmailUnavailable("Unknown reminder category.")
    actual_limit = min(limit, 10) if category == "all" else limit
    queries = SMART_QUERIES if category == "all" else {category: SMART_QUERIES[category]}

    service = _service()  # If OAuth is invalid, report that separately.
    ids = []
    counts = {}
    errors = []
    seen = set()
    for kind, query in queries.items():
        try:
            response = _execute_gmail_request(lambda q=query: service.users().messages().list(
                userId="me", q=q, maxResults=actual_limit, includeSpamTrash=False
            ))
            found = response.get("messages", [])
            counts[kind] = len(found)
            for entry in found:
                try:
                    message_id = _validate_id(entry["id"])
                except (GmailUnavailable, KeyError, TypeError):
                    errors.append({"category": kind, "stage": "message-id", "code": "Invalid ID"})
                    continue
                if message_id not in seen:
                    seen.add(message_id)
                    ids.append(message_id)
        except Exception as exc:
            errors.append({"category": kind, "stage": "search", "code": _gmail_error_code(exc)})
            counts[kind] = 0

    if errors and not ids and len(errors) >= len(queries):
        codes = ", ".join(sorted(set(e["code"] for e in errors)))
        raise GmailUnavailable(f"Gmail search failed ({codes}). If this persists, check Google authorization and API quotas.")

    dated = []
    undated = []
    scanned = 0
    for message_id in ids:
        try:
            # Reduce per-second Gmail API usage during a broad scan.
            time.sleep(0.12)
            message = _execute_gmail_request(lambda mid=message_id: service.users().messages().get(
                userId="me", id=mid, format="full"
            ))
            payload = message.get("payload") or {}
            subject = _header(payload, "Subject") or "(No subject)"
            sender = _header(payload, "From")
            sent = _header(payload, "Date")
            body = extract_body(payload)
            finance = deadline_hints(subject, body, sent)
            other, other_kind = reminder_hints(subject, body, sent)
            hints = finance or other
            for hint in hints:
                dated.append({"message_id": message_id, "subject": subject, "sender": sender, **hint})
            if not hints:
                kind = notice_kind(subject, body) or other_kind
                if kind:
                    undated.append({"message_id": message_id, "subject": subject, "sender": sender, "type": kind})
            scanned += 1
        except Exception as exc:
            # No message bodies/IDs in errors, and no automatic task creation.
            errors.append({"category": "message", "stage": "read/analyze", "code": _gmail_error_code(exc)})
            continue

    if errors and not scanned:
        codes = ", ".join(sorted(set(e["code"] for e in errors)))
        raise GmailUnavailable(f"Could not scan Gmail messages ({codes}). Try a focused category scan.")

    return {
        "items": sort_items(dated), "undated": undated[:50],
        "scanned": scanned, "matched_message_ids": len(ids),
        "searched_categories": counts, "scope": category,
        "limit_per_category": actual_limit, "errors": errors[:20],
        "partial": bool(errors), "saved": False,
        "notice": "Possible reminders only, not verified obligations. Review the source email.",
    }
