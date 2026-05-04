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

### No-code chat flow

Open:

```text
http://localhost:8000/chat
```

For Google OAuth in a remote-server POC, use a localhost SSH tunnel so Google
accepts the redirect URI:

```bash
ssh -L 8017:127.0.0.1:8017 subbrain@10.170.75.180
```

Then open:

```text
http://localhost:8017/chat
```

Add this redirect URI to the Google OAuth client:

```text
http://localhost:8017/oauth/google/callback
```

Paste a Vietnamese use case such as:

```text
Mình làm HR, có Google Sheet quản lý ứng viên và Drive chứa CV.
Muốn upload link CV là tự điền họ tên/email/SĐT/năm sinh,
và mỗi ngày highlight ứng viên apply quá 10 ngày chưa xong process.
```

YAG will:

- infer the workflow goal
- create a no-code workflow blueprint with trigger, nodes, loop mode, and error shield
- ask for missing Google Sheet / Drive inputs
- create the real HR automations automatically when enough inputs are present

Chat API:

```bash
curl -X POST http://localhost:8000/chat/messages \
  -H "Content-Type: application/json" \
  -d '{"message":"paste use case here","session_id":"default"}'
```

Review generated workflow blueprints:

```bash
curl http://localhost:8000/workflows
```

### Direct API flow

1. Open `http://localhost:8000/connect/google`
2. Setup HR automation directly:

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
