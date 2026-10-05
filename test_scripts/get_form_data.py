from pprint import pprint
from playwright.sync_api import sync_playwright

PROFILE = "./playwright/.auth"

# broken 
urls1 = ["https://apply.workable.com/mindex/j/84B10DB922/apply?utm_source=Simplify&ref=Simplify"]

urls2 = ["https://eaiti.applytojob.com/apply/Y16NUsHVnd/Entry-Level-Software-Developer?gh_src=Handshake&iisn=Handshake&iis=Handshake&src=Handshake&source=Handshake&ref=Handshake&utm_medium=Handshake&referral=Handshake&utm_source=Handshake&__jvst=Handshake&__jvsd=Handshake&sourceDetails=Handshake&trid=Handshake&lever-source%5B%5D=Handshake&Source=Handshake&rb=Handshake&jobBoardSource=Handshake&channel=Handshake&rcid=Handshake"]

urls4 = ["https://job-boards.greenhouse.io/embed/job_app?for=databricks&ref=Simplify&token=8847738002&utm_source=Simplify"]

urls3 = ["https://careers.withwaymo.com/jobs/2027-summer-intern-ms-phd-ai-driven-ml-performance-engineering-intern-mountain-view-california-united-states?gh_jid=8248060&ref=Simplify&utm_source=Simplify"]

urls5 = ["https://job-boards.greenhouse.io/arcboatcompany/jobs/5442881008?utm_source=Simplify&ref=Simplify"]

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        PROFILE,
        headless=False
    )

    results = []

    try: 
        for url in urls5:
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

                    # grab the closest parent container and get inner text, walk up DOM tree until find one of these
                    # container_text = field.evaluate("""
                    #     el => {
                    #         const container =
                    #             el.closest('[data-ui="field"]') ||
                    #             el.closest('[data-ui="form-field"]') ||
                    #             el.closest('fieldset') ||
                    #             el.closest('.form-group') ||
                    #             el.parentElement;

                    #         return container ? container.innerText.trim() : null;
                    #     }
                    #     """)

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

                results.append({
                    "url": page.url,
                    "title": page.title(),
                    "form_text": form.all_inner_texts(),
                    "fields": fields
                })

                # field = fields_locator.nth(14)

                # for level in range(1, 8):
                #     text = field.evaluate(
                #         f"""
                #         el => {{
                #             let node = el;
                #             for (let i = 0; i < {level}; i++) {{
                #                 node = node.parentElement;
                #                 if (!node) return null;
                #             }}
                #             return node.innerText?.trim();
                #         }}
                #         """
                #     )

                #     print(f"\nLEVEL {level}:")
                #     print(text)

                # print("\nURL:")
                # print(page.url)

                # print("\nTITLE:")
                # print(page.title())

                # print("\nFORM COUNT:")
                # print(page.locator("form").count())

                # print("\nINPUT COUNT:")
                # print(page.locator("input").count())

                # print("\nTEXTAREA COUNT:")
                # print(page.locator("textarea").count())

                # print("\nSELECT COUNT:")
                # print(page.locator("select").count())

                # print("\nSUBMIT BUTTON COUNT:")
                # print(page.locator('button[type="submit"]').count())

                # print("\nBODY TEXT:")
                # print(page.locator("body").inner_text()[:5000])

                # html = page.content()

                # print("\n'application-form' IN HTML:")
                # print("application-form" in html)

                # print("\n'Submit application' IN HTML:")
                # print("Submit application" in html)
                pprint(results)
                input("Press Enter to close...")

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