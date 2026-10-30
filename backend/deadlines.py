"""Conservative, review-first billing and renewal hints.

A Gmail search match is NOT evidence of money owed. We only suggest deadlines
when a sentence actually describes a bill, a renewal, or a trial ending.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
import re

from .nlp import extract_date

LIMIT = 25

TRIAL = re.compile(r"\b(?:free trial|trial (?:period|ends?|ending|expires?|expir(?:es|ing)|will end|converts?))\b", re.I)
SUBSCRIPTION = re.compile(r"\b(?:subscription|membership|auto[- ]?renew(?:s|al|ing)?|renewal|renews?|recurring billing|plan (?:renewal|renews))\b", re.I)
PAYMENT = re.compile(r"\b(?:invoice|bill(?:ing)?|payment|balance due|minimum due|statement|autopay)\b", re.I)

# Detect an actual event, not merely a marketing keyword or the word 'today'.
TRIAL_EVENT = re.compile(r"\b(?:trial.{0,55}?(?:ends?|ending|expir(?:es|ing)|converts?|will end|is over)|(?:end|expiration) of (?:your |the )?trial)\b", re.I)
SUBSCRIPTION_EVENT = re.compile(r"\b(?:renew(?:s|al|ing)?|auto[- ]?renew(?:s|al|ing)?|membership expires?|subscription (?:expires?|ends?|ending)|plan (?:renews|expires)|(?:next|upcoming) billing date|will be billed|recurring charge)\b", re.I)
PAYMENT_EVENT = re.compile(r"\b(?:payment.{0,25}?due|(?:bill|invoice|balance|amount|minimum).{0,35}?due|due date|pay(?:ment)? by|(?:bill|statement|invoice) (?:is |now )?(?:ready|available)|autopay (?:scheduled|on)|your (?:bill|invoice) is ready|payment required|scheduled payment)\b", re.I)

# Subject-level ad filtering is deliberate: genuine billing emails often have
# "unsubscribe" in their footer, so do not reject merely on that word.
MARKETING = re.compile(
    r"\b(?:special financing|apply (?:now|today|and earn|for a)|"
    r"apply & earn|earn [\d,]+ (?:membership )?(?:rewards|points|miles)|"
    r"membership rewards|refer a friend|referral bonus|"
    r"switch to .{0,45}?(?:get|earn|save)|"
    r"exclusive offer|limited[- ]time offer|"
    r"sign up (?:now|today)|pre[- ]?approved|"
    r"get up to \$[\d,]+|"
    r"cashback offer|bonus points|shop now|sale ends|"
    r"discount code|black friday)\b", re.I
)
RECEIPT = re.compile(
    r"\b(?:payment (?:received|successful|completed|confirmed)|"
    r"paid in full|thank you for (?:your )?payment|"
    r"receipt for|order confirmation|subscription cancelled|"
    r"cancellation confirmed|refund issued|successfully renewed)\b", re.I
)
NUMERIC_US = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
EXPLICIT = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:,?\s*\d{4})?)\b", re.I
)
RELATIVE = re.compile(r"\b(?:today|tomorrow|(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", re.I)


def _reference(sent_date: str, today: date) -> date:
    if not sent_date:
        return today
    try:
        return min(parsedate_to_datetime(sent_date).date(), today)
    except (TypeError, ValueError, OverflowError, IndexError):
        return today


def _has_event(text: str, kind: str) -> bool:
    return bool({
        "trial": TRIAL_EVENT,
        "subscription": SUBSCRIPTION_EVENT,
        "payment": PAYMENT_EVENT,
    }[kind].search(text))


def _kind(text: str) -> str | None:
    """Only classify when the corresponding kind has an event/obligation."""
    if TRIAL.search(text) and _has_event(text, "trial"):
        return "trial"
    if SUBSCRIPTION.search(text) and _has_event(text, "subscription"):
        return "subscription"
    if PAYMENT.search(text) and _has_event(text, "payment"):
        return "payment"
    return None


def notice_kind(subject: str, body: str = "") -> str | None:
    """A high-precision heading/early-body candidate without an extracted date."""
    if MARKETING.search(subject) or RECEIPT.search(subject):
        return None
    heading = subject + "\n" + body[:1400]
    if MARKETING.search(heading[:200]):
        return None
    return _kind(heading)


def _date_on_line(line: str, ref: date, *, event_on_line: bool):
    """Avoid interpreting unqualified 'today' as a billing deadline."""
    numeric = NUMERIC_US.search(line)
    if numeric:
        try:
            return datetime.strptime(numeric.group(1), "%m/%d/%Y").date().isoformat(), numeric.group(1)
        except ValueError:
            return None, None
    if EXPLICIT.search(line):
        return extract_date(line, ref)
    # For relative dates, the *same line* must contain a real billing event.
    if event_on_line and RELATIVE.search(line):
        return extract_date(line, ref)
    return None, None


def deadline_hints(subject: str, body: str, sent_date: str = "", today: date | None = None):
    """Find dated events; no automatic task creation or financial assertions."""
    today = today or date.today()
    if MARKETING.search(subject) or RECEIPT.search(subject):
        return []
    reference = _reference(sent_date, today)
    source = (subject + "\n" + body)[:32000]
    lines = [
        " ".join(p.split())[:500]
        for p in re.split(r"[\r\n]+|(?<=[.!?])\s+(?=[A-Z])", source)
    ]
    lines = [p for p in lines if p]
    hints = []
    for i, line in enumerate(lines):
        if MARKETING.search(line) or RECEIPT.search(line):
            continue
        # Adjacent-line extraction supports e.g. "Renewal date:" then "Nov 8".
        current_event = _kind(line)
        previous = lines[i - 1] if i else ""
        previous_event = _kind(previous) if previous else None
        kind = current_event or (previous_event if len(line) <= 90 else None)
        if not kind:
            continue
        due, expression = _date_on_line(line, reference, event_on_line=bool(current_event))
        if not due:
            continue
        days = (date.fromisoformat(due) - today).days
        if not -30 <= days <= 365:
            continue
        if any(x["due_date"] == due and x["type"] == kind for x in hints):
            continue
        hints.append({
            "type": kind,
            "due_date": due,
            "days_until": days,
            "priority": "overdue" if days < 0 else "soon" if days <= 7 else "upcoming",
            "evidence": line[:350],
            "matched_date": expression,
            "note": "Possible deadline only. Verify the original email and your billing account.",
        })
    return hints[:5]


def sort_items(items):
    return sorted(items, key=lambda x: (x["due_date"], x["subject"].casefold()))
