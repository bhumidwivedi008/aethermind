# AetherMind - Personal AI Chief of Staff
Feature: voice/text note -> prioritized tasks, deadlines and reminders saved to a personal workspace.

Flow: note (text / .txt / voice) -> /api/extract (Gemini or Claude, schema-guided JSON) -> validation ->
user review -> /api/tasks (re-validate) -> SQLite INSERT -> board refresh + confirmation.

## Run locally
    python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env     # add your API key
    python app.py            # http://localhost:5000

## Deploy on Render (one URL serves frontend + backend)
1. Push this folder to GitHub.
2. Render -> New -> Web Service -> pick the repo.
3. Build: `pip install -r requirements.txt`   Start: `gunicorn app:app`
4. Environment: AI_PROVIDER, GEMINI_API_KEY (or ANTHROPIC_API_KEY), optionally DB_PATH.
5. Submit the *.onrender.com URL as your frontend URL.
Note: Render free disks are ephemeral, so SQLite data resets on redeploy. Mention this under Limitations,
or attach a Render Disk / switch to Postgres.

## Test cases for the report
- Success: "Tomorrow send the budget report to Priya, urgent. Remind me Friday 9am to book the venue."
- Missing fields: "Clean up the shared drive sometime" -> warnings for no due date, priority defaults to medium.
- Empty input: click Extract with a blank note -> error message.
- Invalid output: edit a date to garbage via browser dev tools / wrong AI JSON -> 422, card shows "Fix:".
- Failed request: stop the server and click Extract -> "Could not reach the server".
