# job_scraping
This repository contain FastAPI endpoints for playwright browser automation and web scraping for job application descriptions/content.

## Deploy on Render

Commit and push `requirements.txt`, `.python-version`, `main.py`,
and this README to your repository. Create a **Web Service** with these settings:

| Field | Value |
| --- | --- |
| Repository | `https://github.com/mattdavis207/job_scraping` |
| Name | `job-scraping` (or another available name) |
| Branch | `main` |
| Language / Runtime | `Python 3` |
| Region | Choose the region closest to your API consumers |
| Root Directory | Leave blank |
| Build Command | `pip install -r requirements.txt && python -m playwright install chromium` |
| Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1` |
| Pre-Deploy Command | Leave blank |
| Health Check Path | `/health` |
| Environment Variables | `HEADLESS=true`, `PLAYWRIGHT_BROWSERS_PATH=0`, `BROWSER_PROFILE_PATH=/tmp/job-scraping-profile` |
| Auto-Deploy | On Commit, if you want pushes to deploy automatically |
| Instance Type | Choose a plan with enough memory for Chromium; 2 GB is a starting recommendation, not a measured requirement |

The build installs Python dependencies and Chromium. `PLAYWRIGHT_BROWSERS_PATH=0`
keeps the browser installation inside the Playwright package for runtime access.
Render supplies `PORT`; `.python-version` selects Python 3.11.
After deployment, check `/health` and open `/docs` on your Render service URL.

For an existing Docker service, open Settings → Build → Source → Edit, select
the repository, and switch Runtime to Python with the commands above.

Local runs retain a visible browser by default. Set `HEADLESS=true` to run locally
without a browser window.

### Current limitations

- Chromium also requires Linux system libraries. The native runtime has not been
  tested here; if browser launch reports a missing shared library, downloading
  Chromium alone is insufficient. Native builds cannot be assumed to support
  privileged `playwright install --with-deps` installation.
- `BROWSER_PROFILE_PATH` points to a fresh server profile. Authenticated sites
  require separate server-side authentication setup.
- `.auth` is currently tracked in Git and is included in a native checkout.
  The server uses the separate profile path above; avoid committing more profile data.
- The server profile is ephemeral and may be lost on restarts or deployments.
- Both scraping endpoints share one browser profile. Send scraping requests one
  at a time until profile locking or isolated request contexts are implemented.
- `/jd-scrape` currently expects a JSON body on a GET request. Use a client that
  supports this; browser-based Swagger UI may not send it.

References: [Render FastAPI deployment](https://render.com/docs/deploy-fastapi),
[Render native runtimes](https://render.com/docs/native-runtimes),
[Playwright browser installation](https://playwright.dev/python/docs/browsers).
