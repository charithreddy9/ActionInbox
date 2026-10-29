from datetime import date
import os
import pytest
from fastapi.testclient import TestClient
from backend import app as backend_app
from backend.nlp import analyze,extract_date,parse_message,classify
from backend.evaluate import run

TODAY=date(2026,10,29)

def test_deadline_month_and_year_rollover():
    assert extract_date('Pay by November 8',TODAY)[0]=='2026-11-08'
    assert extract_date('Due January 3',TODAY)[0]=='2027-01-03'
    assert extract_date('Submit by 2026-10-31',TODAY)[0]=='2026-10-31'

def test_relative_dates():
    assert extract_date('Reply tomorrow',TODAY)[0]=='2026-10-30'
    assert extract_date('Finish next Tuesday',TODAY)[0]=='2026-11-03'
    assert extract_date('Please write back',TODAY)[0] is None

def test_quote_ignored():
    result=analyze('Hello, thanks for the update.\nOn Tuesday, Alex wrote:\n> Please pay me tomorrow',reference=TODAY)
    assert result['suggestions']==[]

def test_marketing_is_not_an_action():
    result=analyze('Flash sale! Shop now and save 50%.\nOur weekly newsletter arrived.',reference=TODAY)
    assert result['suggestions']==[]

def test_two_suggestions_and_sources():
    result=analyze('Please pay the water bill by November 8. Please upload the signed form by Friday.',reference=TODAY)
    assert len(result['suggestions'])==2
    assert result['suggestions'][0]['due_date']=='2026-11-08'
    assert result['suggestions'][1]['category']=='document'
    assert result['suggestions'][1]['source_excerpt'].startswith('Please upload')
    assert all(x['needs_review'] for x in result['suggestions'])

def test_eml_simple():
    subject,body=parse_message('From: sample@example.org\nSubject: Sample request\n\nPlease confirm our meeting tomorrow.','eml')
    assert subject=='Sample request'
    assert 'meeting' in body

def test_eml_html_body():
    source='MIME-Version: 1.0\nContent-Type: text/html; charset=UTF-8\nSubject: Update\n\n<p>Please send the revised document tomorrow.</p>'
    result=analyze(source,'eml',TODAY)
    assert len(result['suggestions'])==1
    assert '<p>' not in result['suggestions'][0]['title']

def test_empty_rejected():
    with pytest.raises(ValueError):analyze('   ')

def test_intent_examples():
    assert classify('Please pay my internet invoice')[0]=='payment'
    assert classify('Schedule a dentist appointment')[0]=='meeting'
    assert classify('Upload the signed PDF document')[0]=='document'

def test_evaluation_has_all_examples():
    report=run()
    assert report['count']==27
    assert 'confusion_matrix' in report
    assert report['accuracy']>=.4

def test_task_approval_and_dedup(tmp_path,monkeypatch):
    monkeypatch.setattr(backend_app,'DB_PATH',tmp_path/'tasks.sqlite3')
    client=TestClient(backend_app.app)
    msg=client.post('/api/analyze',json={'text':'Please pay the internet bill by November 8.','reference_date':'2026-10-29'}).json()
    assert not client.get('/api/tasks').json() # not saved on analysis
    suggestion=msg['suggestions'][0]
    payload={k:suggestion[k] for k in ('id','message_hash','title','source_excerpt','subject','category','priority','due_date')}
    assert client.post('/api/tasks',json=payload).status_code==201
    assert client.post('/api/tasks',json=payload).status_code==409
    assert len(client.get('/api/tasks').json())==1
    assert client.patch('/api/tasks/'+payload['id'],json={'done':True,'title':'Pay the electricity bill'}).json()['done']
    assert client.delete('/api/tasks/'+payload['id']).status_code==200
    assert client.get('/api/tasks').json()==[]

def test_input_length_limit():
    with pytest.raises(ValueError):analyze('A'*32001)
