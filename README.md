# Bizard Leads

Bizard Leads is an AI-powered outreach automation platform for SMBs. The repo follows a layered monolith shape:

- `backend/app/api/routes` for FastAPI endpoints
- `backend/services` for integrations and business logic
- `backend/workers` for Celery workflows
- `backend/models` and `backend/migrations` for persistence
- `frontend` for the static dashboard and auth pages
- `infra` for nginx and compose-related support files

Current integration workflow:

- Lead discovery: Google Maps scraping -> website parsing -> LinkedIn discovery
- Email generation + verification: pattern generation + SMTP verification
- CRM sync: HubSpot
- Outreach delivery: Mailtrap SMTP
- AI personalization: OpenAI

## Local backend

Use the project venv inside `backend/.venv`:

```powershell
backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

## Full stack

```powershell
docker compose up --build
```
