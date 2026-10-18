# TransOpt AI Team #35 — Shareable Online Demo

This package deploys **one web service**: Docker builds the React app and FastAPI serves both the `/api/*` endpoints and the UI from a single site. Your teammates need only one link.

## Deploy on Render

1. Create a **private** empty GitHub repository (`transopt-team35`). Upload the **contents of this folder**, with `Dockerfile` and `render.yaml` at the repository root. Do **not** upload the sponsor spreadsheets, historical data caches, `.db` files, `.env` files or real customer information.
2. Open https://dashboard.render.com/ and connect your GitHub account.
3. Choose **New > Blueprint**, select your private repository, and approve the service specified in `render.yaml`.
4. Under `TRANSOPT_DEMO_PASSWORD`, enter a strong password to share privately with your team. Do not commit it to GitHub.
5. Confirm the **Free** plan, create the service, and wait until Render reports **Live**. The service URL is on its Render page, something like `https://transopt-team35-demo.onrender.com` (illustrative, not reserved).
6. Open that URL. A browser sign-in prompt should appear. Username: `team`; Password: your Render environment variable. Share the URL and credentials with teammates privately.

**Manual deployment alternative:** New > Web Service > Connect repo > Language `Docker` > plan `Free`; set env vars `TRANSOPT_REQUIRE_AUTH=1` and `TRANSOPT_DEMO_PASSWORD=<strong password>`, and health check `/health`. No separate Vercel or API URL is needed.

## Important limitations

- **Render Free uses ephemeral local storage.** This project still uses SQLite on disk. Orders and truck statuses **will be lost** when the service sleeps/restarts/redeploys. All teammates share the same temporary state while the instance runs. Avoid using this for real orders. Render Free services typically sleep after 15 minutes of inactivity and take time to restart.
- For persistent shared orders, move SQLite to a Render **paid web service with persistent disk** and set `TRANSOPT_DB` to a file within the disk mount point, e.g. `/var/data/transopt_demo.db`, OR migrate to persistent managed PostgreSQL (requires backend code changes). Do not add a paid disk unintentionally.
- The application is a **simulation**, not validated for real dispatch; maps are approximate and some route travel times are synthetic.
- Basic HTTP sign-in is meant for a small private demo, not production authentication with individual permissions or audit logs. Use HTTPS (Render supplies it), a strong password, and synthetic customer data.
- Sponsor historical data exports have been excluded from this package intentionally. The historical APIs remain, but will report that their offline cache is missing.

## Running locally

Two-terminal development remains unchanged:

Backend: `cd backend`, `py -m pip install -r requirements.txt`, `py -m uvicorn main:app --reload --port 8000`

Frontend: `cd frontend`, `npm install`, `npm run dev`

Local dev does not require sign-in unless `TRANSOPT_REQUIRE_AUTH=1` is set.

## Local build tests

The dispatch backend tests and HTTP Basic access were tested successfully. The full React build was **not** verified in the assistant workspace because npm package installation timed out. Render will build the frontend from npm during the deployment. If the build fails, open the Render deployment logs and share the first error.
