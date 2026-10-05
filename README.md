# Job scraping: Render API + local worker

Render stores job-description jobs and results, and serves `/application-questions` directly. `worker.py` runs on the computer where Handshake
works, polls Render over HTTPS, opens Playwright locally, and uploads results.
No inbound port or tunnel is required on the worker computer. Keep it awake and
online. Handshake login state stays on that computer.

## 1. Deploy the queue API on Render

Push the project files, including `queue_api.py` and `worker.py`.
Use a Python web service with these settings:

| Field | Value |
| --- | --- |
| Branch | `main` |
| Runtime | Python 3 |
| Root directory | Leave blank |
| Build command | `pip install -r requirements.txt && python -m playwright install chromium` |
| Start command | `uvicorn queue_api:app --host 0.0.0.0 --port $PORT --workers 1` |
| Health check | `/health` |
| Environment | `QUEUE_API_TOKEN`, `QUEUE_DB_PATH`, `HEADLESS=true`, `PLAYWRIGHT_BROWSERS_PATH=0` |

Generate a random token locally with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
Set that value as `QUEUE_API_TOKEN` on Render and on the worker. Keep it private;
it grants job submission, result access, and worker access. This setup is for one
trusted owner, not separate customer accounts. Do not put the token in public
frontend code.

For durable jobs, attach a Render persistent disk at `/var/data` and set
`QUEUE_DB_PATH=/var/data/jobs.sqlite3`. Persistent disks require a paid service.
Use one service instance: this SQLite queue does not support multiple Render
instances with separate disks. For a temporary test without a disk, use
`QUEUE_DB_PATH=/tmp/jobs.sqlite3`; jobs and results can disappear on redeployment
or restart. Completed results currently remain in the database until you remove
them; no automatic retention policy is implemented.

Render needs Chromium for direct application-form requests. Keep `HEADLESS=true`
and `PLAYWRIGHT_BROWSERS_PATH=0` on Render. No Handshake secret file is needed there;
application forms use a fresh anonymous browser context. The start command stays
**queue_api:app**. `/jd-scrape` is not exposed on this app; use the queue for job
descriptions. Chromium's Linux library compatibility must still be verified on
Render; unrelated sites may also apply access restrictions.

### Direct application questions (no queue)

Send `POST /application-questions` with the same bearer token and a JSON body:

```json
{"urls": ["https://example.com/careers/apply"]}
```

This accepts non-Handshake URLs and returns the existing list of application
results in the same HTTP response. No job ID, polling, or local worker is needed.
Large batches can take longer than a client/proxy timeout; use small batches.
Only one direct application request runs at a time per server process. Overlapping
requests receive HTTP 429 with `Retry-After: 10`; retry after that delay (with a
bounded retry count). Keep `--workers 1` and one Render instance for this limit.
The slot is released even when scraping fails. A single Chromium browser can
still exceed the instance memory limit on a heavy page; monitor Render memory.

## 2. Authenticate and start the worker on your computer

From the project directory:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python test_scripts/get_profile.py
```

In the opened browser, log in and open a job description, then press Enter in
the terminal to save `playwright/.auth/handshake.json`. Skip this login step if
that file already contains your working session.

Then set configuration and run the worker:

```bash
export QUEUE_API_URL='https://YOUR-SERVICE.onrender.com'
read -rs 'QUEUE_API_TOKEN?Paste your queue token: '
export QUEUE_API_TOKEN
export HEADLESS=false
export HANDSHAKE_STORAGE_STATE="$PWD/playwright/.auth/handshake.json"
python worker.py
```

The hidden token prompt above is for macOS's default zsh. The worker uses existing
scraping functions in `main.py`. Keep the terminal running. Stop with Ctrl+C.
If login expires, stop the worker, rerun the login script, and restart it.
Do not copy Render's `PLAYWRIGHT_BROWSERS_PATH=0` into your local environment unless
you also installed Chromium with that setting.

## 3. Submit a job and retrieve the result

From a trusted client/terminal with `QUEUE_API_URL` and `QUEUE_API_TOKEN` set:

```bash
curl -sS "$QUEUE_API_URL/jobs" \
  -H "Authorization: Bearer $QUEUE_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"kind":"job_description","url":"https://app.joinhandshake.com/job-search/11307575"}'
```

The API responds HTTP 202 with `{"id":"...","status":"queued"}`. Copy the id:

```bash
curl -sS "$QUEUE_API_URL/jobs/JOB_ID" \
  -H "Authorization: Bearer $QUEUE_API_TOKEN"
```

Poll every few seconds until `status` is `completed` or `failed`. On completion,
`result.job_description` contains the extracted text. Submit one URL per job.
For application forms, use the direct `/application-questions` route above.
The previous queued application kind remains accepted for compatibility.
The `/jobs` queue accepts only HTTPS `joinhandshake.com` URLs and its subdomains;
this restriction does not apply to the direct application route.
The existing scraper can follow site redirects; only trusted callers should
have access to the queue token.

A job stays `queued` when no worker is online. Workers claim one job at a time,
renew a five-minute lease every 30 seconds, and retry network failures. A worker
that crashes or loses connectivity stops renewing its lease; another poll can
reclaim that job. Delivery is at least once, so interrupted jobs can run again.
A `running` job with an expired lease is reclaimed when a worker next polls.

This architecture uses your working local browser environment; it does not
guarantee future Handshake access or automatically solve authentication challenges.
Watch the **local worker terminal** for browser errors and Render logs for API errors.
Login state and browser profiles must not be committed. The root `.auth` directory
was already tracked in this repository; adding an ignore rule does not remove
previously committed files or history.

## Checks

The tests use FastAPI's TestClient and require `httpx` in your development environment:

```bash
python -m unittest discover -s tests -v
```

Install test dependencies with `pip install -r requirements-dev.txt` first.
