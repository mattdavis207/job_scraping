from fastapi import FastAPI, Query
from typing import Annotated
from pathlib import Path
import os
from playwright.sync_api import sync_playwright
from pydantic import BaseModel

PROFILE = Path(os.getenv("BROWSER_PROFILE_PATH", str(Path(__file__).resolve().parent / ".auth")))
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

class JobScrapeRequest(BaseModel):
    urls: list[str]

class ApplicationQuestionsRequest(BaseModel):
    urls: list[str]

@app.get("/jd-scrape")
def get_job_description(request: JobScrapeRequest):
    with sync_playwright() as p:
        # context = p.chromium.launch_persistent_context(
        #     PROFILE,
        #     headless=HEADLESS
        # )
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            storage_state="/etc/secrets/handshake.json"
        )

        results = []

        try: 
            for url in request.urls:
                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded")
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

                        job_desc_div.wait_for(
                            state="visible", timeout=60_000
                        )

                        # click more button
                        job_desc_div.get_by_text("More", exact=True).click()

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
                    results.append({
                        "url": url,
                        "error": str(e)
                    })
                    # print(f"Failed: {url}: {e}")
                finally:
                    page.close()
        finally:
            context.close()
            browser.close()
    
    return results


@app.post("/application-questions")
def application_questions(request: ApplicationQuestionsRequest):
    results = []

    for url in request.urls:
        result = scrape_application(url)
        results.append(result)

    return {"applications": results}




def scrape_application(url):
    with sync_playwright() as p:
        # context = p.chromium.launch_persistent_context(
        #     PROFILE,
        #     headless=HEADLESS
        # )  
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            storage_state="/etc/secrets/handshake.json"
        )

        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded")
            print(page.title())

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
            return{
                "url": url,
                "error": str(e)
            }
        finally:
            try:
                page.close()     
            finally: 
                context.close()
                browser.close()
