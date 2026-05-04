# YAG HR Automation POC

Backend-only POC for the HR workflow in `GUIDE.md`.

It proves:

- Google OAuth connect
- Google Sheet exploration and missing-column setup
- Google Drive CV reading
- Gemma/OpenAI-compatible CV extraction
- Google Sheet append/update and overdue highlighting
- Manual run endpoints, logs, and APScheduler jobs

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Create a Google OAuth Desktop/Web client and either set `GOOGLE_CLIENT_SECRET_FILE`
or `GOOGLE_CLIENT_ID` plus `GOOGLE_CLIENT_SECRET`.

## API flow

1. Open `http://localhost:8000/connect/google`
2. Setup HR automation:

```bash
curl -X POST http://localhost:8000/automations/hr/setup \
  -H "Content-Type: application/json" \
  -d '{
    "sheet_url": "https://docs.google.com/spreadsheets/d/xxx/edit",
    "sheet_name": "Candidates",
    "drive_folder_url": "https://drive.google.com/drive/folders/yyy",
    "max_days_in_process": 10
  }'
```

3. Test a CV:

```bash
curl -X POST http://localhost:8000/automations/auto_cv_extract_default/cv-link \
  -H "Content-Type: application/json" \
  -d '{"cv_url":"https://drive.google.com/file/d/xxx/view"}'
```

4. Run overdue checker:

```bash
curl -X POST http://localhost:8000/automations/auto_overdue_default/run
```

5. View logs:

```bash
curl http://localhost:8000/automations/auto_overdue_default/runs
```

