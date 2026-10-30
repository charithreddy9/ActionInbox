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


def test_transactional_trial_email_yields_one_relevant_suggestion():
    from datetime import date
    text=(
      "Make the most of your 4% APY with Gold.\n"
      "Take advantage of a high yield and start earning more.\n"
      "As a reminder, your Gold free trial ends tomorrow. "
      "You’ll be charged $5/month to your Robinhood brokerage account when your free trial ends.\n"
      "The 3% matching on contributions requires a subscription with Robinhood Gold.\n"
      "Customers must stay subscribed for 1 year.\n"
      "The funds that earned the match must be kept for 5 years.\n"
      "The annual tax filing deadline typically is April 15th.\n"
      "You must have compensation to contribute to an IRA.\n"
      "Robinhood does not provide tax advice; please consult with a tax adviser if you have questions.\n"
    )
    result=analyze(text,reference=date(2026,10,29),subject_override="Your free trial is ending")
    assert len(result["suggestions"])==1
    one=result["suggestions"][0]
    assert "free-trial" in one["title"]
    assert one["due_date"]=="2026-10-30"
    assert "trial ends tomorrow" in one["source_excerpt"]
    assert one["needs_review"] and one["category"]=="payment"


def test_transactional_trial_with_repeated_text_not_duplicated():
    from datetime import date
    text="As a reminder, your Gold free trial ends tomorrow.\n" * 3
    result=analyze(text,reference=date(2026,10,29),subject_override="Your free trial is ending")
    assert len(result["suggestions"])==1


def test_ordinary_email_still_extracts_three_distinct_actions():
    from datetime import date
    text=("Please update my resume by November 3, 2026.\n"
          "Send the completed project report by November 5, 2026.\n"
          "Schedule a meeting by November 9, 2026.")
    result=analyze(text,reference=date(2026,10,30),subject_override="ActionInbox Test")
    assert len(result["suggestions"])==3


def test_repeated_generic_request_does_not_double_create_task():
    from datetime import date
    text="Please upload the signed lease form by Friday.\nPlease upload the signed lease form by Friday."
    result=analyze(text,reference=date(2026,10,30))
    assert len(result["suggestions"])==1


def test_undated_trial_remains_reviewable_without_invented_date():
    from datetime import date
    result=analyze("Your Gold free trial is ending soon.",reference=date(2026,10,30),subject_override="Your free trial is ending")
    assert len(result["suggestions"])==1
    assert result["suggestions"][0]["due_date"] is None
