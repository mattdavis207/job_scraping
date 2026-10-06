"""Run on the computer where your Handshake login works."""
import json
import logging
import os
import ssl
import certifi
from pathlib import Path
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    base = os.environ["QUEUE_API_URL"].strip().rstrip("/")
    token = os.environ["QUEUE_API_TOKEN"]
    parsed = urlsplit(base)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise SystemExit("QUEUE_API_URL must be the service base URL, without /jobs or credentials")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")):
        raise SystemExit("QUEUE_API_URL must use HTTPS (except localhost)")
    os.environ.setdefault("HANDSHAKE_STORAGE_STATE", str(
        Path(__file__).resolve().parent / "playwright/.auth/handshake.json"))
    if not Path(os.environ["HANDSHAKE_STORAGE_STATE"]).is_file():
        raise SystemExit("Run python test_scripts/get_profile.py first, or set HANDSHAKE_STORAGE_STATE")

    # Import after configuring the local browser environment.
    from main import JobScrapeRequest, get_job_description, scrape_application
    from queue_api import NewJob

    tls_context = ssl.create_default_context(cafile=os.getenv("SSL_CERT_FILE") or certifi.where())

    def post(path, body):
        request = Request(base + path, data=json.dumps(body).encode(), method="POST",
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urlopen(request, timeout=30, context=tls_context) as response:
            return json.load(response)

    def keep_alive(job, stop):
        while not stop.wait(30):
            try:
                post(f"/worker/{job['id']}/heartbeat", {"claim_token": job["claim_token"]})
            except (HTTPError, URLError, TimeoutError):
                logging.warning("Heartbeat failed for job %s; retrying", job["id"])

    logging.info("Worker ready; polling %s. Press Ctrl+C to stop.", base)
    while True:
        try:
            job = post("/worker/claim", {}).get("job")
            if job is None:
                time.sleep(5)
                continue
            logging.info("Processing job %s", job["id"])
            stop = threading.Event()
            thread = threading.Thread(target=keep_alive, args=(job, stop), daemon=True)
            thread.start()
            try:
                payload = {"claim_token": job["claim_token"]}
                try:
                    validated = NewJob(kind=job["kind"], url=job["url"])
                    if validated.kind == "job_description":
                        result = get_job_description(JobScrapeRequest(urls=[validated.url]))[0]
                    else:
                        result = scrape_application(validated.url)
                    if result is None:
                        payload["error"] = "No application form result returned"
                    else:
                        payload["result"] = result
                        if result.get("error"):
                            # Do not upload exception strings that can contain SSO URLs.
                            payload["result"] = None
                            payload["error"] = "Scrape failed; inspect local worker logs and refresh login if needed"
                except Exception as exc:
                    payload["error"] = f"Worker failed ({type(exc).__name__}); inspect local setup"
                for attempt in range(5):
                    try:
                        post(f"/worker/{job['id']}/complete", payload)
                        logging.info("Job %s: %s", job["id"], "failed" if payload.get("error") else "completed")
                        break
                    except HTTPError as exc:
                        if exc.code < 500:
                            raise
                        if attempt == 4:
                            raise
                        time.sleep(5)
                    except (URLError, TimeoutError):
                        if attempt == 4:
                            raise
                        time.sleep(5)
            finally:
                stop.set()
                thread.join(timeout=35)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise SystemExit("Queue authentication failed; check QUEUE_API_TOKEN") from None
            logging.warning("Queue HTTP error %s; retrying in 10 seconds", exc.code)
            time.sleep(10)
        except (URLError, TimeoutError) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            logging.warning("Queue unavailable (%s: %s); retrying in 10 seconds",
                            type(reason).__name__, reason)
            time.sleep(10)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        main()
    except KeyboardInterrupt:
        print("Worker stopped. Unfinished jobs become available again after the lease expires.")
