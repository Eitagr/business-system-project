# Run and update this app

## Local

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create a file named `.env` in the same folder as `app.py` (the project root).
It is not a folder, and it is gitignored.

```
GEMINI_API_KEY=your-key
SESSION_SECRET=any-long-random-string
```

- `GEMINI_API_KEY` — required for the live chat (Google AI Studio). Without
  it the chat shows «חסר מפתח Gemini» and will not extract a name.
- `SESSION_SECRET` — any long random string

```
.venv/bin/uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

The chat header must read **Gemini פעיל**. Staff pages are in the top nav.

Pasted golden conversation (identification → clarification → ID → date
correction): [DEMO.md](DEMO.md).

Submission scenarios (no API key, no network — a local NLU double):

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

Keep the same `.env` on the server (it is gitignored), including
`GEMINI_API_KEY`. Then restart the process that runs uvicorn.

If it was started in a terminal:

```
# stop the old process (Ctrl+C), then:
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
```

If it runs under a process manager, restart that unit instead of starting a second copy, for example:

```
sudo systemctl restart atlas
```

Do this every time `git pull` brings new commits. There is no deploy CI/CD;
the loop is always pull, install if requirements changed, restart.

## Code review on pull requests

`.github/workflows/code-review.yml` runs Gemini on the PR diff and posts a
comment. This is review only — it does not deploy.

1. Repo **Settings → Secrets and variables → Actions → New repository secret**
2. Name `GEMINI_API_KEY`, same value as in `.env`
3. Open a pull request; the **Gemini code review** check should comment

Without that secret the workflow fails on purpose.

Optional plugins (a click on the GitHub account, not something the repo can
do by itself):

- [GitHub Copilot code review](https://github.com/apps/github-copilot-code-review) — install the app, then on a PR use **Copilot → Review**
- [Cursor Bugbot](https://cursor.com/docs/bugbot) — connect the GitHub app for Cursor reviews on PRs
