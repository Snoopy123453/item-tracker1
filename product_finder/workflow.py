from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

DB_PATH = Path('data/project_workflow.db')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: str | Path = DB_PATH) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS projects (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      project_number TEXT DEFAULT '',
      client TEXT DEFAULT '',
      manager TEXT DEFAULT '',
      status TEXT DEFAULT 'Active',
      due_date TEXT DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS approvals (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id INTEGER NOT NULL,
      item_tag TEXT DEFAULT '',
      division TEXT DEFAULT '',
      product TEXT NOT NULL,
      manufacturer TEXT DEFAULT '',
      model TEXT DEFAULT '',
      reviewer TEXT DEFAULT '',
      due_date TEXT DEFAULT '',
      status TEXT DEFAULT 'Needs review',
      priority TEXT DEFAULT 'Normal',
      decision_note TEXT DEFAULT '',
      updated_at TEXT NOT NULL,
      FOREIGN KEY(project_id) REFERENCES projects(id)
    );
    CREATE TABLE IF NOT EXISTS workflow_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id INTEGER NOT NULL,
      approval_id INTEGER,
      event_type TEXT NOT NULL,
      detail TEXT DEFAULT '',
      actor TEXT DEFAULT '',
      created_at TEXT NOT NULL
    );
    ''')
    return conn


def create_project(name: str, project_number: str = '', client: str = '', manager: str = '', due_date: str = '', path: str | Path = DB_PATH) -> int:
    now = _now()
    with _connect(path) as conn:
        cur = conn.execute('INSERT INTO projects(name,project_number,client,manager,due_date,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                           (name.strip(), project_number.strip(), client.strip(), manager.strip(), due_date, now, now))
        return int(cur.lastrowid)


def list_projects(path: str | Path = DB_PATH) -> pd.DataFrame:
    with _connect(path) as conn:
        return pd.read_sql_query('SELECT * FROM projects ORDER BY updated_at DESC', conn)


def add_approval(project_id: int, product: str, item_tag: str = '', division: str = '', manufacturer: str = '', model: str = '', reviewer: str = '', due_date: str = '', priority: str = 'Normal', path: str | Path = DB_PATH) -> int:
    now = _now()
    with _connect(path) as conn:
        cur = conn.execute('''INSERT INTO approvals(project_id,item_tag,division,product,manufacturer,model,reviewer,due_date,priority,updated_at)
                              VALUES(?,?,?,?,?,?,?,?,?,?)''',
                           (project_id,item_tag,division,product,manufacturer,model,reviewer,due_date,priority,now))
        approval_id = int(cur.lastrowid)
        conn.execute('INSERT INTO workflow_events(project_id,approval_id,event_type,detail,created_at) VALUES(?,?,?,?,?)',
                     (project_id,approval_id,'Created',f'Approval item created for {product}',now))
        return approval_id


def list_approvals(project_id: int, path: str | Path = DB_PATH) -> pd.DataFrame:
    with _connect(path) as conn:
        return pd.read_sql_query('SELECT * FROM approvals WHERE project_id=? ORDER BY updated_at DESC', conn, params=(project_id,))


def save_approvals(project_id: int, frame: pd.DataFrame, actor: str = '', path: str | Path = DB_PATH) -> None:
    now = _now()
    with _connect(path) as conn:
        for row in frame.to_dict('records'):
            approval_id = int(row['id'])
            old = conn.execute('SELECT status FROM approvals WHERE id=?', (approval_id,)).fetchone()
            conn.execute('''UPDATE approvals SET item_tag=?,division=?,product=?,manufacturer=?,model=?,reviewer=?,due_date=?,status=?,priority=?,decision_note=?,updated_at=? WHERE id=? AND project_id=?''',
                         (str(row.get('item_tag','')),str(row.get('division','')),str(row.get('product','')),str(row.get('manufacturer','')),str(row.get('model','')),str(row.get('reviewer','')),str(row.get('due_date','')),str(row.get('status','Needs review')),str(row.get('priority','Normal')),str(row.get('decision_note','')),now,approval_id,project_id))
            if old and old['status'] != row.get('status'):
                conn.execute('INSERT INTO workflow_events(project_id,approval_id,event_type,detail,actor,created_at) VALUES(?,?,?,?,?,?)',
                             (project_id,approval_id,'Status changed',f"{old['status']} -> {row.get('status')}",actor,now))


def project_metrics(project_id: int, path: str | Path = DB_PATH) -> dict[str, Any]:
    df = list_approvals(project_id, path)
    if df.empty:
        return {'total':0,'approved':0,'needs_review':0,'overdue':0,'completion':0.0}
    today = datetime.now().date().isoformat()
    approved = int(df['status'].isin(['Approved','Quoted','Ordered','Received','Installed']).sum())
    overdue = int(((df['due_date'].fillna('') < today) & (df['due_date'].fillna('') != '') & ~df['status'].isin(['Approved','Rejected','Ordered','Received','Installed'])).sum())
    return {'total':len(df),'approved':approved,'needs_review':int((df['status']=='Needs review').sum()),'overdue':overdue,'completion':round(approved/len(df)*100,1)}


def list_events(project_id: int, path: str | Path = DB_PATH) -> pd.DataFrame:
    with _connect(path) as conn:
        return pd.read_sql_query('SELECT * FROM workflow_events WHERE project_id=? ORDER BY created_at DESC', conn, params=(project_id,))
