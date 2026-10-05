from fastapi import FastAPI, Query
from typing import Annotated
from pathlib import Path
import os
import json
import logging
from contextlib import contextmanager
from urllib.parse import urlsplit
from uuid import uuid4
from playwright.sync_api import sync_playwright
from pydantic import BaseModel

PROFILE = Path(os.getenv("BROWSER_PROFILE_PATH", str(Path(__file__).resolve().parent / ".auth")))
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"

app = FastAPI()
logger = logging.getLogger("uvicorn.error")


def log_scrape(event, **details):
    logger.info("scrape %s", json.dumps({"event": event, **details}))


def safe_location(url):
    # Never log query strings, fragments, or credentials from SSO redirects.
    parsed = urlsplit(url)
    return {"host": parsed.hostname, "path": parsed.path}


@contextmanager
def authenticated_context(playwright, *, use_handshake=True):
    state_path = Path(os.getenv("HANDSHAKE_STORAGE_STATE", "/etc/secrets/handshake.json"))
    if use_handshake:
        log_scrape("auth_file", exists=state_path.is_file(), headless=HEADLESS)
    browser = None
    stage = "browser_launch"
    try:
        log_scrape(stage)
        browser = playwright.chromium.launch(headless=HEADLESS, timeout=30_000)
        stage = "load_auth_state" if use_handshake else "anonymous_context"
        log_scrape(stage)
        context = browser.new_context(**(
            {"storage_state": str(state_path)} if use_handshake else {}
        ))
        context.set_default_timeout(15_000)
        context.set_default_navigation_timeout(30_000)
        log_scrape("context_ready")
    except Exception as exc:
        log_scrape("setup_failed", stage=stage, error_type=type(exc).__name__)
        if browser is not None:
            browser.close()
        raise
    try:
        yield context
    finally:
        try:
            context.close()
        finally:
            browser.close()


def attach_diagnostics(page, request_id):
    page.on("crash", lambda _: log_scrape("page_crashed", request_id=request_id))
    page.on("pageerror", lambda _: log_scrape("javascript_error", request_id=request_id))
    page.on("requestfailed", lambda request: log_scrape(
        "request_failed", request_id=request_id, resource_type=request.resource_type,
        **safe_location(request.url)))
    page.on("response", lambda response: log_scrape(
        "http_error", request_id=request_id, status=response.status,
        **safe_location(response.url)) if response.status >= 400 else None)


def log_page_failure(page, request_id, stage, exc):
    details = {}
    try:
        details = {**safe_location(page.url),
                   "password_inputs": page.locator('input[type="password"]').count(),
                   "job_description_headings": page.get_by_role(
                       "heading", name="Job description", exact=True).count()}
    except Exception:
        pass
    log_scrape("failed", request_id=request_id, stage=stage,
               error_type=type(exc).__name__, **details)

@app.get("/health")
def health():
    return {"status": "ok"}

class JobScrapeRequest(BaseModel):
    urls: list[str]

class ApplicationQuestionsRequest(BaseModel):
    urls: list[str]

@app.get("/jd-scrape")
def get_job_description(request: JobScrapeRequest):
    with sync_playwright() as p, authenticated_context(p) as context:
        results = []

        try: 
            for url in request.urls:
                page = context.new_page()
                request_id = uuid4().hex[:12]
                attach_diagnostics(page, request_id)
                stage = "navigation"

                try:
                    log_scrape(stage, request_id=request_id, **safe_location(url))
                    response = page.goto(url, wait_until="domcontentloaded")
                    log_scrape(
                        "response_check",
                        request_id=request_id,
                        status=response.status if response else None,
                        cloudflare_challenge=(
                            response.headers.get("cf-mitigated") == "challenge"
                            if response else False
                        ),
                    )
                    log_scrape("navigated", request_id=request_id,
                               status=response.status if response else None,
                               **safe_location(page.url))
                    # print(page.title())
                    
                    handshake_url = "handshake" in url.lower()

                    # Handshake extraction
                    if handshake_url:
                        job_section = page.locator("div").filter(
                        has=page.locator(
                            ':scope > div > h3',
                            has_text="Job description"
                        ))


                        job_desc_div = job_section.locator(":scope > div").nth(1)

                        stage = "job_description_selector"
                        log_scrape(stage, request_id=request_id)
                        job_desc_div.wait_for(state="visible", timeout=15_000)

                        # click more button
                        stage = "expand_description"
                        more = job_desc_div.get_by_text("More", exact=True)
                        if more.count() and more.first.is_visible():
                            more.first.click()

                        results.append({
                            "url": url,
                            "job_description": job_desc_div.inner_text()
                        })

                        # print(f"Collected: {url}")
                    else:
                        selectors = [
                            "main",
                            "article",
                            '[role="main"]'
                        ]

                        page_text = None

                        for selector in selectors:
                            locator = page.locator(selector)

                            if locator.count() > 0:
                                text = locator.first.inner_text().strip()

                                if len(text) > 500:
                                    page_text = text
                                    break

                        if not page_text:
                            page_text = page.locator("body").inner_text()

                        results.append({
                            "url": url,
                            "job_description": page_text
                        })

                except Exception as e:
                    log_page_failure(page, request_id, stage, e)
                    results.append({
                        "url": url,
                        "error": str(e)
                    })

                finally:
                    log_scrape("finished", request_id=request_id)
                    page.close()
        finally:
            log_scrape("batch_finished")
    
    return results


@app.post("/application-questions")
def application_questions(request: ApplicationQuestionsRequest):
    results = []

    for url in request.urls:
        result = scrape_application(url)
        results.append(result)

    return results




def scrape_application(url):
    with sync_playwright() as p, authenticated_context(p, use_handshake=False) as context:
        page = context.new_page()
        request_id = uuid4().hex[:12]
        attach_diagnostics(page, request_id)
        stage = "navigation"
        try:
            log_scrape(stage, request_id=request_id, **safe_location(url))
            response = page.goto(url, wait_until="domcontentloaded")
            log_scrape("navigated", request_id=request_id,
                       status=response.status if response else None,
                       **safe_location(page.url))
            stage = "application_form"

            page.wait_for_timeout(5000)

            form = page.locator("form")
            
            fields_locator = form.locator(
                'input:not([type="hidden"]), textarea, select'
            )

            fields = []

            for i in range(fields_locator.count()):
                field = fields_locator.nth(i)

                # Match field id to label
                field_id = field.get_attribute("id")
                label = None

                if field_id:
                    label_locator = form.locator(f'label[for="{field_id}"]')

                    if label_locator.count() > 0:
                        label = label_locator.first.inner_text().strip()

                # collect candidate levels for LLM to interpret relevant question
                ancestor_candidates = field.evaluate("""
                    el => {
                        const candidates = [];
                        const seen = new Set();
                        let node = el.parentElement;

                        for (let level = 1; node && level <= 8; level++) {
                            const text = (node.innerText || "").trim();

                            if (
                                text &&
                                !seen.has(text) &&
                                text.length < 500
                            ) {
                                candidates.push({
                                    level: level,
                                    tag: node.tagName.toLowerCase(),
                                    text: text
                                });

                                seen.add(text);
                            }

                            node = node.parentElement;
                        }

                        return candidates;
                    }
                    """)

                fields.append({
                    "index": i,
                    "tag": field.evaluate("el => el.tagName.toLowerCase()"),
                    "type": field.get_attribute("type"),
                    "name": field.get_attribute("name"),
                    "id": field.get_attribute("id"),
                    "label": label,
                    "ancestor_candidates": ancestor_candidates,
                    "placeholder": field.get_attribute("placeholder"),
                    "required": (
                        field.get_attribute("required") is not None
                        or field.get_attribute("aria-required") == "true"
                    ),
                    "aria_label": field.get_attribute("aria-label"),
                    "value": field.input_value()
                        if field.evaluate(
                            "el => ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)"
                        )
                        else None
                })

            return {
                "url": page.url,
                "title": page.title(),
                "form_text": form.all_inner_texts(),
                "fields": fields
            }
        except Exception as e:
            log_page_failure(page, request_id, stage, e)
            return{
                "url": url,
                "error": str(e)
            }
        finally:
            log_scrape("finished", request_id=request_id)
            page.close()
