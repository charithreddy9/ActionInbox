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
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.words = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("div", "p", "br", "li"):
            self.words.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        elif tag in ("div", "p", "li"):
            self.words.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.words.append(data)

    def text(self):
        return "".join(self.words)


def _decode(data):
    if not isinstance(data, str) or not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise GmailUnavailable("The selected Gmail message contains invalid text encoding.") from exc


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
        if content_type == "text/plain":
            plain.append(raw)
        elif content_type == "text/html":
            parser = _HTMLText()
            parser.feed(raw)
            html.append(parser.text())
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    body = "\n".join(plain).strip() or "\n".join(html).strip()
    return body[:MAX_BODY]


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
