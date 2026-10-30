"""Review-first email extraction: local TF-IDF intent model plus transparent rules."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta, datetime
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import hashlib
import re
from functools import lru_cache

import numpy as np
from dateutil.parser import parse as parse_date
from sklearn.pipeline import make_pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from .training import EXAMPLES

MAX_INPUT=32000
ACTION_RE = re.compile(r"\b(please|could you|can you|would you|need to|must|remember to|don't forget|submit|upload|send|reply|respond|confirm|schedule|book|pay|settle|review|sign|complete|renew|follow up|let me know|due|deadline|appointment|interview|registration|rsvp)\b",re.I)
STOP_RE = re.compile(r"\b(unsubscribe|shop now|save \d+%|limited offer|exclusive discount|flash sale|click here to buy)\b", re.I)
URGENT_RE = re.compile(r"\b(urgent|asap|immediately|overdue|final reminder|past due|critical)\b",re.I)
DATEWORDS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
MONTHDAY=re.compile(rf"\b({DATEWORDS}\s+\d{{1,2}}(?:,?\s*\d{{4}})?)\b",re.I)
NUMERIC_DATE=re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
RELATIVE_DATE=re.compile(r"\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\b(today|tomorrow)\b",re.I)
INTRO_RE=re.compile(r"\b(by|before|due|deadline|on|scheduled for|appointment|until|no later than|at)\b",re.I)

@lru_cache(maxsize=1)
def classifier():
    x,y=[],[]
    for label,samples in EXAMPLES.items():
        x.extend(samples);y.extend([label]*len(samples))
    model=make_pipeline(TfidfVectorizer(ngram_range=(1,2),sublinear_tf=True),LogisticRegression(max_iter=500,random_state=13))
    model.fit(x,y)
    return model

class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__();self.buf=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
        elif tag in ('p','div','br','li'):self.buf.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style') and self.skip:self.skip-=1
        elif tag in ('p','div','li'):self.buf.append('\n')
    def handle_data(self,data):
        if not self.skip:self.buf.append(data)
    def result(self):return ''.join(self.buf)

def parse_message(text,format='text'):
    if not text or not text.strip():raise ValueError('Enter an email message first.')
    if len(text)>MAX_INPUT:raise ValueError('Message is too long (32,000 character limit).')
    if format=='text':return '',text
    if format!='eml':raise ValueError('Supported formats are text and eml.')
    msg=BytesParser(policy=policy.default).parsebytes(text.encode('utf-8'))
    subject=str(msg.get('subject',''))[:180]
    body=msg.get_body(preferencelist=('plain','html')) if msg.is_multipart() else msg
    if body is None:body=msg
    value=body.get_content()
    if isinstance(value,bytes):value=value.decode('utf-8',errors='replace')
    if body.get_content_type()=='text/html':
        parser=_TextOnly();parser.feed(value);value=parser.result()
    return subject,value[:MAX_INPUT]

def clean_body(body):
    # Ignore signature/forwarded conversation after common delimiters.
    lines=[]
    for line in body.splitlines():
        line=line.strip()
        if re.match(r'^(>+|On .+ wrote:|-----Original Message-----|From:\s|Sent:\s)',line,re.I):break
        if line in ('--','-- '):break
        if line:lines.append(line)
    return '\n'.join(lines)

def sentences(body):
    for line in clean_body(body).splitlines():
        # Do not fragment email addresses or decimal values; sentence breaks require whitespace.
        for part in re.split(r'(?<=[.!?])\s+(?=[A-Z])',line):
            part=part.strip()
            if part:yield part

def extract_date(text,reference:date):
    # A date is only inferred if the actual text contains a supported date expression.
    m=NUMERIC_DATE.search(text)
    if m:
        try:return date.fromisoformat(m.group(1)).isoformat(),m.group(1)
        except ValueError:return None,None
    m=MONTHDAY.search(text)
    if m:
        raw=m.group(1)
        try:
            day=parse_date(raw,default=datetime(reference.year,1,1)).date()
            if not re.search(r'\b\d{4}\b',raw) and day<reference:day=day.replace(year=day.year+1)
            return day.isoformat(),raw
        except (ValueError,OverflowError):return None,None
    m=RELATIVE_DATE.search(text)
    if not m:return None,None
    token=m.group(0).lower().strip()
    if token=='today':return reference.isoformat(),token
    if token=='tomorrow':return (reference+timedelta(days=1)).isoformat(),token
    weekday=['monday','tuesday','wednesday','thursday','friday','saturday','sunday'].index(m.group(2).lower())
    delta=(weekday-reference.weekday())%7
    if delta==0:delta=7
    # "next Tuesday" means the upcoming Tuesday, including next week if necessary.
    return (reference+timedelta(days=delta)).isoformat(),token

def classify(sentence):
    scores=classifier().predict_proba([sentence])[0]
    labels=classifier().classes_
    ix=int(np.argmax(scores))
    category=str(labels[ix]);score=float(scores[ix])
    # Clear user-visible cues can override weak statistical classification.
    if re.search(r'\b(bill|invoice|payment|pay|balance due|premium)\b',sentence,re.I):category='payment'
    elif re.search(r'\b(appointment|meeting|interview|schedule|reservation|book a call)\b',sentence,re.I):category='meeting'
    elif re.search(r'\b(attachment|upload|document|form|signature|signed|paperwork|contract)\b',sentence,re.I):category='document'
    elif re.search(r'\b(reply|respond|let me know|write back)\b',sentence,re.I):category='reply'
    return category,round(score,3)

def analyze(text,format='text',reference=None,subject_override=None):
    reference=reference or date.today()
    subject,body=parse_message(text,format)
    if subject_override is not None and format=="text":
        subject=subject_override[:180]
    candidates=[]
    clean=clean_body(body)
    fingerprint=hashlib.sha256((subject+'\n'+clean).encode()).hexdigest()
    for sentence in sentences(body):
        if not ACTION_RE.search(sentence) or STOP_RE.search(sentence):continue
        if len(sentence)<12:continue
        category,score=classify(sentence)
        if category=='other' and score>0.32:continue
        due,matched=extract_date(sentence,reference)
        reasons=[]
        if matched:reasons.append('Date mentioned: '+matched)
        if URGENT_RE.search(sentence):reasons.append('Urgent language in message')
        days=(date.fromisoformat(due)-reference).days if due else None
        priority='high' if URGENT_RE.search(sentence) or (days is not None and days<=2) else 'medium' if days is not None and days<=7 else 'normal'
        if days is not None and days<0:reasons.append('Date appears to be in the past; please verify')
        reasons.append('Category suggested from text (model + keyword rules)')
        task_id=hashlib.sha256((fingerprint+'\n'+sentence).encode()).hexdigest()[:20]
        candidates.append(dict(id=task_id,title=sentence[:180],source_excerpt=sentence[:350],category=category,
            model_score=score,priority=priority,due_date=due,date_expression=matched,reasons=reasons,
            message_hash=fingerprint,subject=subject,needs_review=True))
    return dict(subject=subject,message_hash=fingerprint,reference_date=reference.isoformat(),
        suggestions=candidates[:12],total_candidates=len(candidates),discarded_over_limit=max(0,len(candidates)-12),
        privacy_note='Message text is analyzed locally and not stored. Only approved task excerpts are saved.')
