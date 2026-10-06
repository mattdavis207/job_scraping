"""Render API: queued job descriptions and direct application-form scraping."""
import hmac
import json
import os
import sqlite3
import time
from threading import Lock
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, field_validator
from main import ApplicationQuestionsRequest, application_questions

app = FastAPI(title="Scraping job queue")
LEASE_SECONDS = 300
# This limit is per process; deploy with --workers 1 and one Render instance.
application_scrape_lock = Lock()


def authenticate(authorization: str = Header(default="")):
    token = os.getenv("QUEUE_API_TOKEN", "")
    if not token:
        raise HTTPException(503, "QUEUE_API_TOKEN is not configured")
    if not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "Invalid bearer token")


@app.post("/application-questions", dependencies=[Depends(authenticate)])
def direct_application_questions(request: ApplicationQuestionsRequest):
    if not application_scrape_lock.acquire(blocking=False):
        raise HTTPException(
            429, "An application scrape is already running. Retry shortly.",
            headers={"Retry-After": "10"},
        )
    try:
        return application_questions(request)
    finally:
        application_scrape_lock.release()


@contextmanager
def database():
    path = Path(os.getenv("QUEUE_DB_PATH", "data/jobs.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, url TEXT NOT NULL,
            status TEXT NOT NULL, created REAL NOT NULL, lease_until REAL,
            claim_token TEXT, result TEXT, error TEXT)""")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class NewJob(BaseModel):
    kind: Literal["job_description", "application_questions"] = "job_description"
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or not (host == "joinhandshake.com" or host.endswith(".joinhandshake.com"))
                or parsed.port not in (None, 443)):
            raise ValueError("Use an HTTPS joinhandshake.com URL")
        return value


class Claim(BaseModel):
    claim_token: str


class Completion(Claim):
    result: dict | list | None = None
    error: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/jobs", status_code=202, dependencies=[Depends(authenticate)])
def submit(job: NewJob):
    job_id = uuid4().hex
    with database() as db:
        db.execute("INSERT INTO jobs(id, kind, url, status, created) VALUES(?,?,?,?,?)",
                   (job_id, job.kind, job.url, "queued", time.time()))
    return {"id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}", dependencies=[Depends(authenticate)])
def get_job(job_id: str):
    with database() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Unknown job")
    return {"job_description_results": 
            {"id": row["id"], "kind": row["kind"], "url": row["url"],
            "status": row["status"], "error": row["error"],
            "result": json.loads(row["result"]) if row["result"] else None}
        }


@app.post("/worker/claim", dependencies=[Depends(authenticate)])
def claim():
    now = time.time()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT * FROM jobs WHERE status='queued'
            OR (status='running' AND lease_until < ?) ORDER BY created LIMIT 1""",
                         (now,)).fetchone()
        if row is None:
            return {"job": None}
        token = uuid4().hex
        db.execute("UPDATE jobs SET status='running', claim_token=?, lease_until=? WHERE id=?",
                   (token, now + LEASE_SECONDS, row["id"]))
        return {"job": {"id": row["id"], "kind": row["kind"], "url": row["url"],
                        "claim_token": token}}


@app.post("/worker/{job_id}/heartbeat", dependencies=[Depends(authenticate)])
def heartbeat(job_id: str, body: Claim):
    with database() as db:
        updated = db.execute("""UPDATE jobs SET lease_until=? WHERE id=?
            AND status='running' AND claim_token=? AND lease_until>=?""",
            (time.time() + LEASE_SECONDS, job_id, body.claim_token, time.time()))
        if updated.rowcount != 1:
            raise HTTPException(409, "Job lease lost")
    return {"ok": True}


@app.post("/worker/{job_id}/complete", dependencies=[Depends(authenticate)])
def complete(job_id: str, body: Completion):
    with database() as db:
        updated = db.execute("""UPDATE jobs SET status=?, result=?, error=?
            WHERE id=? AND status='running' AND claim_token=? AND lease_until>=?""",
            ("failed" if body.error else "completed", json.dumps(body.result), body.error,
             job_id, body.claim_token, time.time()))
        if updated.rowcount != 1:
            # A repeated delivery after a lost HTTP response is safe.
            row = db.execute("SELECT status, claim_token FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["claim_token"] != body.claim_token or row["status"] not in ("completed", "failed"):
                raise HTTPException(409, "Job lease lost")
    return {"ok": True}
