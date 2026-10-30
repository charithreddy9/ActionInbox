"""Review-first subscription, trial and payment deadline hints from Gmail.
Heuristics only: never claim a charge is owed without user verification.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
import re
from .nlp import extract_date

TYPES = {
 "subscription": re.compile(r"\b(subscription|membership|renew(?:al|s|ing)?|auto.?renew|recurring|billing cycle)\b",re.I),
 "payment": re.compile(r"\b(invoice|bill(?:ing)?|payment|amount due|balance due|minimum due|pay by|statement balance|credit card due)\b",re.I),
 "trial": re.compile(r"\b(free trial|trial ends?|trial expires?|trial period|trial converts?|trial will end)\b",re.I),
}
DATE_SIGNAL=re.compile(r"\b(due|by|before|on|renew|renewal|renews|expire|expires|ending|ends|charge|charged|bill|billing|payment|trial)\b",re.I)
NEGATIVE=re.compile(r"\b(payment (?:received|successful|completed|confirmed)|paid in full|receipt|thank you for (?:your )?payment|successfully renewed|subscription cancelled|cancellation confirmed|refund issued)\b",re.I)
PROMO=re.compile(r"\b(unsubscribe|shop now|exclusive offer|sale ends|save \d+%|discount code|black friday)\b",re.I)
LIMIT=25

def _reference(sent_date, today):
    if not sent_date:return today
    try:
        parsed=parsedate_to_datetime(sent_date).date()
        return min(parsed,today)
    except (TypeError,ValueError,OverflowError,IndexError):return today

def deadline_hints(subject, body, sent_date="", today=None):
    today=today or date.today()
    source=(subject+"\n"+body)[:32000]
    ref=_reference(sent_date,today)
    snippets=re.split(r"[\n\r]+|(?<=[.!?])\s+(?=[A-Z])",source)
    results=[]
    for item in snippets:
        text=" ".join(item.split())[:350]
        if len(text)<12 or PROMO.search(text) or NEGATIVE.search(text):continue
        found=extract_date(text,ref)
        due,expression=found
        if not due or not DATE_SIGNAL.search(text):continue
        days=(date.fromisoformat(due)-today).days
        if days < -30 or days > 365:continue
        combined=(subject+" "+text)
        category=next((kind for kind in ("trial","subscription","payment") if TYPES[kind].search(combined)),None)
        if not category:continue
        # Explicitly request review for inferred calendar dates and charge status.
        if any(x["due_date"]==due and x["type"]==category for x in results):continue
        results.append(dict(type=category,due_date=due,days_until=days,
                            priority="overdue" if days<0 else "soon" if days<=7 else "upcoming",
                            evidence=text,matched_date=expression,
                            note="Possible deadline, not a verified charge. Check the original email and billing account."))
    return results[:5]

def sort_items(items):
    return sorted(items,key=lambda x:(x["due_date"],x["subject"].casefold()))
