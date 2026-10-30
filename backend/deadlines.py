"""Review-first subscription, trial and payment deadline hints from Gmail.
Heuristics only: never claim a charge is owed without user verification.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
import re
from .nlp import extract_date
from dateutil.parser import parse as parse_datetime

TYPES = {
 "subscription": re.compile(r"\b(subscription|membership|renew(?:al|s|ing)?|auto.?renew|recurring|billing cycle)\b",re.I),
 "payment": re.compile(r"\b(invoice|bill(?:ing)?|payment|amount due|balance due|minimum due|pay by|statement balance|credit card due)\b",re.I),
 "trial": re.compile(r"\b(free trial|trial ends?|trial expires?|trial period|trial converts?|trial will end)\b",re.I),
}
DATE_SIGNAL=re.compile(r"\b(due|by|before|on|renew|renewal|renews|expire|expires|ending|ends|charge|charged|bill|billing|payment|trial)\b",re.I)
NEGATIVE=re.compile(r"\b(payment (?:received|successful|completed|confirmed)|paid in full|receipt|thank you for (?:your )?payment|successfully renewed|subscription cancelled|cancellation confirmed|refund issued)\b",re.I)
PROMO=re.compile(r"\b(unsubscribe|shop now|exclusive offer|sale ends|save \d+%|discount code|black friday)\b",re.I)
LIMIT=25
NUMERIC_US = re.compile(r"\b(?:(?:due|by|before|on|renews?|renewal|expires?|ends?|billing date|payment date)\s*(?:date|is|:|on)?\s*)(\d{1,2}/\d{1,2}/\d{2,4})\b",re.I)
STATUS_RECEIPT = re.compile(r"\b(receipt|payment received|payment successful|payment completed|paid in full|order confirmation|thank you for your payment|subscription cancelled|cancellation confirmed)\b",re.I)
def _find_date(text,ref):
    due,raw=extract_date(text,ref)
    if due:return due,raw
    m=NUMERIC_US.search(text)
    if m:
        try:
            d=parse_datetime(m.group(1),dayfirst=False).date()
            return d.isoformat(),m.group(1)
        except (ValueError,OverflowError):pass
    return None,None


def _reference(sent_date, today):
    if not sent_date:return today
    try:
        parsed=parsedate_to_datetime(sent_date).date()
        return min(parsed,today)
    except (TypeError,ValueError,OverflowError,IndexError):return today

def deadline_hints(subject, body, sent_date="", today=None):
    today=today or date.today()
    ref=_reference(sent_date,today)
    source=(subject+"\n"+body)[:32000]
    lines=[re.sub(r"\s+"," ",p).strip()[:500] for p in re.split(r"[\r\n]+|(?<=[.!?])\s+(?=[A-Z])",source)]
    lines=[s for s in lines if s]
    results=[]
    if STATUS_RECEIPT.search(subject):return results
    for idx,line in enumerate(lines):
        window=" ".join(lines[max(0,idx-1):min(len(lines),idx+2)])[:1000]
        if PROMO.search(line) or NEGATIVE.search(line):continue
        if not re.search(r"\b(due|by|before|renews?|renewal|expires?|ends?|billing|payment|charge(?:d)?|will be billed)\b",window,re.I):continue
        typ=next((kind for kind in ("trial","subscription","payment") if TYPES[kind].search(subject+" "+window)),None)
        if not typ:continue
        due,expression=_find_date(line,ref)
        if not due:continue
        days=(date.fromisoformat(due)-today).days
        if days < -30 or days > 365:continue
        if any(x["due_date"]==due and x["type"]==typ for x in results):continue
        results.append(dict(type=typ,due_date=due,days_until=days,
            priority="overdue" if days<0 else "soon" if days<=7 else "upcoming",
            evidence=line[:350],matched_date=expression,
            note="Possible deadline. Verify the original email and billing account."))
    return results[:5]

def sort_items(items):
    return sorted(items,key=lambda x:(x["due_date"],x["subject"].casefold()))
