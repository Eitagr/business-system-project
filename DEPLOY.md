# Run and update this app

## Local

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

- `GEMINI_API_KEY` — Google AI Studio key (chat still runs the golden Hebrew utterance without it)
- `SESSION_SECRET` — any long random string

```
.venv/bin/uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

Chat is `/`. Staff pages are in the top nav. Submission scenarios:

```
.venv/bin/python check_chat.py
```

## Server (repeatable)

The app is not auto-deployed. After a code change, on the machine that serves it:

```
cd /path/to/business-system-project
git pull
.venv/bin/pip install -r requirements.txt
```

Keep the same `.env` on the server (it is gitignored). Then restart the process that runs uvicorn.

If it was started in a terminal:

```
# stop the old process (Ctrl+C), then:
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
```

If it runs under a process manager, restart that unit instead of starting a second copy, for example:

```
sudo systemctl restart atlas
```

Do this every time `git pull` brings new commits. There is no CI/CD; the loop is always pull, install if requirements changed, restart.
