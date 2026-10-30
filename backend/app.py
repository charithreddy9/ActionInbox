"""Local-only API. Not intended for deployment to the public Internet."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import date,datetime,timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal

from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field

from .nlp import analyze

ROOT=Path(__file__).resolve().parents[1]
DB_PATH=Path(os.getenv('ACTIONINBOX_DB',str(ROOT/'data'/'tasks.sqlite3')))
app=FastAPI(title='ActionInbox',version='0.1.0',docs_url='/api/docs',openapi_url='/api/openapi.json')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],allow_credentials=False,allow_methods=['GET','POST','PATCH','DELETE'],allow_headers=['Content-Type'])

class MessageIn(BaseModel):
    text:str=Field(min_length=1,max_length=32000)
    format:Literal['text','eml']='text'
    reference_date:date|None=None
    subject:str=Field(default='',max_length=180)
class TaskIn(BaseModel):
    id:str=Field(pattern=r'^[a-f0-9]{20}$')
    message_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    title:str=Field(min_length=2,max_length=180)
    source_excerpt:str=Field(min_length=1,max_length=350)
    subject:str=Field(default='',max_length=180)
    category:Literal['payment','meeting','document','reply','other']
    priority:Literal['normal','medium','high']='normal'
    due_date:date|None=None
class TaskEdit(BaseModel):
    title:str|None=Field(default=None,min_length=2,max_length=180)
    due_date:date|None=None
    category:Literal['payment','meeting','document','reply','other']|None=None
    priority:Literal['normal','medium','high']|None=None
    done:bool|None=None

@contextmanager
def connection():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DB_PATH,timeout=5)
    db.row_factory=sqlite3.Row
    try:
        db.execute('''CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY,message_hash TEXT NOT NULL,title TEXT NOT NULL,
          source_excerpt TEXT NOT NULL,subject TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL,priority TEXT NOT NULL,due_date TEXT,
          done INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL
        )''')
        db.commit()
        yield db
        db.commit()
    finally:db.close()

def load_task(row):
    obj=dict(row);obj['done']=bool(obj['done']);return obj

@app.get('/api/health')
def health():return {'ok':True,'mode':'local-first','paid_ai':False,'remote_email_access':False}

@app.post('/api/analyze')
def do_analyze(message:MessageIn):
    try:return analyze(message.text,message.format,message.reference_date, subject_override=message.subject if message.subject else None)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@app.get('/api/tasks')
def get_tasks():
    with connection() as db:
        rows=db.execute('SELECT * FROM tasks ORDER BY done ASC, CASE priority WHEN "high" THEN 0 WHEN "medium" THEN 1 ELSE 2 END, due_date IS NULL ASC, due_date ASC,created_at DESC').fetchall()
    return [load_task(r) for r in rows]

@app.post('/api/tasks',status_code=201)
def save_task(task:TaskIn):
    # A suggestion is never saved until the user clicks Approve. Original email is not persisted.
    with connection() as db:
        try:
            db.execute('''INSERT INTO tasks (id,message_hash,title,source_excerpt,subject,category,priority,due_date,created_at)
                  VALUES (?,?,?,?,?,?,?,?,?)''',(task.id,task.message_hash,task.title,task.source_excerpt,task.subject,task.category,task.priority,
                  str(task.due_date) if task.due_date else None,datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:raise HTTPException(409,'This suggestion was already added.')
        row=db.execute('SELECT * FROM tasks WHERE id=?',(task.id,)).fetchone()
    return load_task(row)

@app.patch('/api/tasks/{task_id}')
def edit_task(task_id:str,change:TaskEdit):
    changes=change.model_dump(exclude_unset=True)
    if not changes:raise HTTPException(400,'No changes supplied.')
    fields=[];values=[]
    for key,value in changes.items():
        fields.append(f'{key}=?')
        values.append(int(value) if key=='done' and value is not None else str(value) if key=='due_date' and value else value)
    with connection() as db:
        result=db.execute(f'UPDATE tasks SET {", ".join(fields)} WHERE id=?',values+[task_id])
        if result.rowcount==0:raise HTTPException(404,'Task not found.')
        row=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
    return load_task(row)

@app.delete('/api/tasks/{task_id}')
def delete_task(task_id:str):
    with connection() as db:
        result=db.execute('DELETE FROM tasks WHERE id=?',(task_id,))
        if result.rowcount==0:raise HTTPException(404,'Task not found.')
    return {'deleted':True}

@app.get('/api/evaluation')
def evaluation():
    p=ROOT/'research'/'evaluation.json'
    if not p.exists():raise HTTPException(404,'Run python -m backend.evaluate to generate the evaluation report.')
    return json.loads(p.read_text(encoding='utf-8'))

@app.get('/')
def home():
    index=ROOT/'frontend'/'dist'/'index.html'
    if index.exists():return FileResponse(index)
    return {'app':'ActionInbox','frontend':'Run npm run dev in frontend/','api_docs':'/api/docs'}

# Single-service hosting is possible, but authentication must be implemented first.
# No general catch-all static mount here to avoid exposing private files on local disk.

# Opt-in Gmail integration: read-only access, manual message selection,
# and no background synchronization. Never log OAuth tokens or full email text.
@app.get('/api/gmail/status')
def gmail_status():
    from .gmail import connection_status
    return connection_status()

@app.get('/api/gmail/messages')
def gmail_messages(q: str = 'in:inbox newer_than:14d', limit: int = 10):
    from .gmail import GmailUnavailable, list_messages
    try:
        return list_messages(q, limit)
    except GmailUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc

@app.get('/api/gmail/messages/{message_id}')
def gmail_message(message_id: str):
    from .gmail import GmailUnavailable, get_message
    try:
        return get_message(message_id)
    except GmailUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc

@app.get('/api/gmail/deadlines')
def gmail_deadlines(limit:int=20):
    from .gmail import GmailUnavailable,scan_deadlines
    try:return scan_deadlines(limit)
    except GmailUnavailable as exc:raise HTTPException(503,str(exc)) from exc
