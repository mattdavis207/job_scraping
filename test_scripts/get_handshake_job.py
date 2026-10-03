from playwright.sync_api import sync_playwright

PROFILE = "./playwright/.auth"

urls = ["https://pitt.joinhandshake.com/job-search/11343311?page=1&per_page=25"]

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        PROFILE,
        headless=False
    )

    results = []

    try: 
        for url in urls:
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded")
                print(page.title())

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

                print(f"Collected: {url}")
                input("")

            except Exception as e:
                results.append({
                    "url": url,
                    "error": str(e)
                })
                print(f"Failed: {url}: {e}")
            finally:
                page.close()
    finally:
        context.close()