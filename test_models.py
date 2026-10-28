import os, time, requests
from dotenv import load_dotenv
load_dotenv(override=True)
key = os.environ.get("GEMINI_API_KEY")

r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                 params={"key": key, "pageSize": 100}, timeout=30).json()
if "error" in r:
    print("KEY ERROR:", r["error"].get("message")); raise SystemExit
names = [m["name"].split("/")[-1] for m in r.get("models", [])
         if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in m["name"]]
print("Flash models on your key:", names, "\n")

for n in names[:8]:
    t = time.time()
    try:
        x = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{n}:generateContent",
            params={"key": key}, timeout=40,
            json={"contents": [{"parts": [{"text": "Reply with the word OK"}]}]})
        print(f"{n:40} {x.status_code}  {time.time()-t:.1f}s")
    except Exception as e:
        print(f"{n:40} {type(e).__name__}  {time.time()-t:.1f}s")