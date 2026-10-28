"""AetherMind - Personal AI Chief of Staff (voice/text note -> prioritized tasks)."""
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
import json, os, re, sqlite3, time
from datetime import date, datetime
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, g

load_dotenv(override=True)
app = Flask(__name__, static_folder="static", static_url_path="")
DB = os.environ.get("DB_PATH", "aethermind.db")
PRIORITIES = {"high", "medium", "low"}
MAX_INPUT = 6000

# ---------- Database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    c = g.pop("db", None)
    if c:
        c.close()

def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            notes TEXT,
            priority TEXT NOT NULL CHECK(priority IN ('high','medium','low')),
            due_date TEXT,
            reminder_at TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            source_text TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
init_db()

# ---------- Schema-guided prompt ----------
SCHEMA = """{
  "tasks": [
    {
      "title":         "string, imperative, max 120 chars (required)",
      "notes":         "string or null - extra context from the note",
      "priority":      "one of: high | medium | low, or null if not stated or implied",
      "due_date":      "YYYY-MM-DD or null if no deadline is stated",
      "reminder_at":   "YYYY-MM-DDTHH:MM or null if no reminder time is stated"
    }
  ]
}"""

def build_prompt(text):
    return f"""You are the task-extraction engine of a personal chief-of-staff app.
Today is {date.today().isoformat()} ({date.today().strftime('%A')}). Resolve relative dates ("tomorrow", "next Friday") from today.
Extract every actionable task from the note below.

Return ONLY valid JSON matching this schema (no markdown, no commentary):
{SCHEMA}

Rules:
- NEVER invent values. If priority, due_date or reminder_at is not stated or clearly implied, use null.
- "urgent", "asap", "critical" => high. "whenever", "if time permits" => low.
- If the note contains no actionable task, return {{"tasks": []}}.

NOTE:
\"\"\"{text}\"\"\""""

# ---------- AI providers ----------
def call_ai(prompt):
    provider = os.environ.get("AI_PROVIDER", "gemini").lower()

    if provider == "anthropic":
        akey = os.environ.get("ANTHROPIC_API_KEY")
        if not akey:
            raise RuntimeError("ANTHROPIC_API_KEY is not set on the server.")
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=40,
            headers={"x-api-key": akey, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5"), "max_tokens": 1500,
                  "messages": [{"role": "user", "content": prompt}]})
        if not r.ok:
            raise RuntimeError(f"AI provider error {r.status_code}: {r.text[:300]}")
        return r.json()["content"][0]["text"]

    gkey = os.environ.get("GEMINI_API_KEY")
    if not gkey:
        raise RuntimeError("GEMINI_API_KEY is not set on the server.")
    models = [m for m in [os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
                          os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.8-flash-lite")] if m]
    last = "No AI model is configured."
    for model in models:
        for attempt in range(2):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    params={"key": gkey}, timeout=60,
                    json={"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}})
            except requests.RequestException as e:
                last = f"AI provider did not respond (model {model}): {type(e).__name__}"
                time.sleep(1)
                continue
            if r.ok:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            last = f"AI provider error {r.status_code} (model {model}): {r.text[:200]}"
            if r.status_code in (429, 500, 503):
                time.sleep(2 * (attempt + 1))
                continue
            break
    raise RuntimeError(last)


def parse_json(raw):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    return json.loads(raw)

# ---------- Validation ----------
def validate_task(t):
    """Returns (clean_task, issues). issues: {field, level: error|warn, msg}."""
    issues, clean = [], {}
    if not isinstance(t, dict):
        return {}, [{"field": "task", "level": "error", "msg": "Task is not an object."}]
    title = (str(t.get("title") or "")).strip()
    if not title:
        issues.append({"field": "title", "level": "error", "msg": "Title is missing."})
    elif len(title) > 120:
        title = title[:120]; issues.append({"field": "title", "level": "warn", "msg": "Title was shortened to 120 characters."})
    clean["title"] = title
    clean["notes"] = (str(t["notes"]).strip() or None) if t.get("notes") else None

    p = (str(t.get("priority") or "")).strip().lower() or None
    if p is None:
        issues.append({"field": "priority", "level": "warn", "msg": "No priority found. Defaulting to medium."}); p = "medium"
    elif p not in PRIORITIES:
        issues.append({"field": "priority", "level": "error", "msg": f"'{p}' is not high, medium or low."})
    clean["priority"] = p

    d = t.get("due_date") or None
    if d:
        try: datetime.strptime(str(d), "%Y-%m-%d")
        except ValueError:
            issues.append({"field": "due_date", "level": "error", "msg": f"'{d}' is not a valid date (YYYY-MM-DD)."}); 
        else:
            if str(d) < date.today().isoformat():
                issues.append({"field": "due_date", "level": "warn", "msg": "Due date is in the past."})
    else:
        issues.append({"field": "due_date", "level": "warn", "msg": "No due date found."}); d = None
    clean["due_date"] = d

    r = t.get("reminder_at") or None
    if r:
        try: datetime.strptime(str(r), "%Y-%m-%dT%H:%M")
        except ValueError:
            issues.append({"field": "reminder_at", "level": "error", "msg": f"'{r}' is not a valid reminder time."})
    clean["reminder_at"] = r
    return clean, issues

# ---------- API ----------
@app.get("/")
def index():
    return app.send_static_file("index.html")

@app.post("/api/extract")
def extract():
    """Text -> AI -> schema-guided JSON -> validation. Returns a preview; nothing is saved yet."""
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return jsonify(error="Add a note first. The note is empty."), 400
    if len(text) > MAX_INPUT:
        return jsonify(error=f"Note is too long. Keep it under {MAX_INPUT} characters."), 400
    try:
        data = parse_json(call_ai(build_prompt(text)))
        raw_tasks = data["tasks"]
        if not isinstance(raw_tasks, list): raise ValueError("'tasks' is not a list")
    except RuntimeError as e:
        return jsonify(error=str(e)), 500
    except requests.RequestException as e:
        return jsonify(error=f"The AI service could not be reached ({type(e).__name__}: {str(e)[:200]})."), 502
    except (ValueError, KeyError, IndexError, TypeError):
        return jsonify(error="The AI returned output that did not match the schema. Try rewording the note."), 502
    tasks = []
    for t in raw_tasks:
        clean, issues = validate_task(t)
        tasks.append({"task": clean, "issues": issues})
    return jsonify(tasks=tasks, source_text=text)

@app.post("/api/tasks")
def create_tasks():
    """User-confirmed tasks are re-validated server-side, then inserted."""
    body = request.get_json(silent=True) or {}
    items, source = body.get("tasks"), body.get("source_text")
    if not isinstance(items, list) or not items:
        return jsonify(error="No tasks to save."), 400
    cleaned, problems = [], []
    for i, t in enumerate(items):
        clean, issues = validate_task(t)
        errs = [x for x in issues if x["level"] == "error"]
        if errs: problems.append({"index": i, "issues": errs})
        cleaned.append(clean)
    if problems:
        return jsonify(error="Some tasks have invalid fields.", problems=problems), 422
    saved = []
    for c in cleaned:
        cur = db().execute(
            "INSERT INTO tasks(title,notes,priority,due_date,reminder_at,source_text) VALUES(?,?,?,?,?,?)",
            (c["title"], c["notes"], c["priority"], c["due_date"], c["reminder_at"], source))
        saved.append(cur.lastrowid)
    db().commit()
    rows = db().execute(f"SELECT * FROM tasks WHERE id IN ({','.join('?'*len(saved))})", saved).fetchall()
    return jsonify(saved=[dict(r) for r in rows]), 201

@app.get("/api/tasks")
def list_tasks():
    rows = db().execute("""SELECT * FROM tasks ORDER BY status='done',
        CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
        due_date IS NULL, due_date""").fetchall()
    return jsonify(tasks=[dict(r) for r in rows])

@app.patch("/api/tasks/<int:tid>")
def update_task(tid):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("open", "done"):
        return jsonify(error="Status must be 'open' or 'done'."), 400
    cur = db().execute("UPDATE tasks SET status=? WHERE id=?", (status, tid)); db().commit()
    if cur.rowcount == 0: return jsonify(error="Task not found."), 404
    return jsonify(ok=True)

@app.delete("/api/tasks/<int:tid>")
def delete_task(tid):
    db().execute("DELETE FROM tasks WHERE id=?", (tid,)); db().commit()
    return jsonify(ok=True)

from werkzeug.exceptions import HTTPException

@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    app.logger.exception(e)
    return jsonify(error=f"Server error: {type(e).__name__}: {str(e)[:200]}"), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
