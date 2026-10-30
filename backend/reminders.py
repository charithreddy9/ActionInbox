"""Conservative nonfinancial deadline detection. All results require review."""
from __future__ import annotations
from datetime import date
from email.utils import parsedate_to_datetime
import re
from .nlp import extract_date
from .deadlines import MARKETING, RECEIPT, _date_on_line

CATEGORIES={
 "travel":r"(?:luggage|baggage|pickup|pick-up|drop[- ]off|lugless|travel)",
 "flight":r"(?:flight|check[- ]in|boarding pass|departure|gate|airport)",
 "appointment":r"(?:appointment|reservation|booking|interview|meeting|visit scheduled)",
 "delivery":r"(?:package|parcel|delivery|collect|pick[- ]?up|locker)",
 "document":r"(?:submit|upload|application|document|paperwork|form|verification|deadline)",
}
EVENTS={
 "travel":r"(?:pickup|pick[- ]up|drop[- ]off|scheduled|reminder|deadline|by|before)",
 "flight":r"(?:check[- ]in|depart(?:s|ure)?|boarding|scheduled|reminder)",
 "appointment":r"(?:appointment|reservation|booking|interview|scheduled|reminder)",
 "delivery":r"(?:pick[- ]?up|collection|collect by|deadline|available for pickup|delivery scheduled)",
 "document":r"(?:submit|upload|due|deadline|complete by|before|required by)",
}
AD=re.compile(r"\b(?:shop now|exclusive offer|limited.time offer|refer a friend|sale ends|save \d+%|new arrivals|discount code|claim your free trial)\b",re.I)
NON_EVENTS=re.compile(r"\b(?:has been delivered|was delivered|order delivered|order shipped|shipped \d+ items|your order shipped|out for delivery|thank you for your order|order placed|order confirmation)\b",re.I)
STRONG=re.compile(r"\b(?:pickup reminder|luggage pickup|pick[- ]?up is scheduled|pick[- ]?up by|check[- ]in opens|boarding starts|appointment reminder|appointment scheduled|flight departs|submission deadline|submit by|must upload|complete your application by|package ready for pickup|collect your package by)\b",re.I)
def _type(text):
    if re.search(r"\\b(?:package|parcel|locker)\\b",text,re.I) and re.search(EVENTS["delivery"],text,re.I):return "delivery"
    for kind in ("travel","flight","appointment","delivery","document"):
        if re.search(CATEGORIES[kind],text,re.I) and re.search(EVENTS[kind],text,re.I):return kind
    return None

def reminder_hints(subject,body,sent_date="",today=None):
    today=today or date.today()
    if MARKETING.search(subject) or AD.search(subject) or RECEIPT.search(subject) or NON_EVENTS.search(subject):
        return [],None
    first=subject+" "+body[:900]
    kind=_type(subject) or (_type(first) if STRONG.search(first) else None)
    if not kind:return [],None
    try:reference=parsedate_to_datetime(sent_date).date() if sent_date else today
    except (TypeError,ValueError,OverflowError,IndexError):reference=today
    lines=[p.strip()[:450] for p in re.split(r"[\r\n]+|(?<=[.!?])\s+(?=[A-Z])",subject+"\n"+body[:20000]) if p.strip()]
    alerts=[]
    for i,line in enumerate(lines):
        if AD.search(line) or NON_EVENTS.search(line):continue
        context=(lines[i-1]+" " if i else "")+line
        if not _type(context) and not STRONG.search(context):continue
        due,matched=_date_on_line(line,reference,event_on_line=bool(_type(line) or STRONG.search(line)))
        if not due:continue
        days=(date.fromisoformat(due)-today).days
        if not -30<=days<=365:continue
        if any(x["due_date"]==due for x in alerts):continue
        alerts.append(dict(type=kind,due_date=due,days_until=days,
              priority="overdue" if days<0 else "soon" if days<=7 else "upcoming",
              evidence=line,note="Possible reminder only; verify the original email."))
    return alerts[:3],kind
