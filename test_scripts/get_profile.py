from pathlib import Path
from playwright.sync_api import sync_playwright

destination = Path("playwright/.auth/handshake.json")
destination.parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://pitt.joinhandshake.com/")

    input(
        "Log in, open a job, and confirm its description is visible. "
        "Then press Enter here..."
    )

    context.storage_state(path=str(destination), indexed_db=True)
    browser.close()