# job_scraping
This repository contain FastAPI endpoints for playwright browser automation and web scraping for job application descriptions/content.

## Deploy on Render

Commit and push `requirements.txt`, `Dockerfile`, `.dockerignore`, `main.py`,
and this README to your repository. Create a **Web Service** with these settings:

| Field | Value |
| --- | --- |
| Repository | `https://github.com/mattdavis207/job_scraping` |
| Name | `job-scraping` (or another available name) |
| Branch | `main` |
| Language / Runtime | `Docker` |
| Region | Choose the region closest to your API consumers |
| Root Directory | Leave blank |
| Dockerfile Path | `./Dockerfile` |
| Docker Build Context | `.` (if shown) |
| Docker Command | Leave blank; uses the Dockerfile CMD |
| Build Command / Start Command | Not needed for Docker |
| Pre-Deploy Command | Leave blank |
| Health Check Path | `/health` |
| Registry Credential | None; the base image is public |
| Environment Variables | None required; `HEADLESS=true` is set in the image and Render supplies `PORT` |
| Auto-Deploy | On Commit, if you want pushes to deploy automatically |
| Instance Type | Choose a plan with enough memory for Chromium; 2 GB is a starting recommendation, not a measured requirement |

The container installs Python dependencies, Chromium, and its Linux libraries.
It starts `uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1`.
After deployment, check `/health` and open `/docs` on your Render service URL.

Local runs retain a visible browser by default. Set `HEADLESS=true` to run locally
without a browser window.

### Current limitations

- The image excludes `.auth` and `.env`. Local login sessions are not deployed;
  authenticated sites require separate server-side authentication setup.
- `.auth` is currently tracked in Git. Excluding it from Docker does not remove
  browser cookies or history from the repository; avoid committing more profile data.
- The server profile is ephemeral and may be lost on restarts or deployments.
- Both scraping endpoints share one browser profile. Send scraping requests one
  at a time until profile locking or isolated request contexts are implemented.
- `/jd-scrape` currently expects a JSON body on a GET request. Use a client that
  supports this; browser-based Swagger UI may not send it.

References: [Render Docker deployment](https://render.com/docs/docker),
[Playwright Docker documentation](https://playwright.dev/python/docs/docker).
