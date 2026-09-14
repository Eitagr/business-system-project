# Appointment management system

Small-business customers, appointments, leads, and receipts, configured
through `config.yaml`, plus a Hebrew chat that identifies a customer,
verifies a national ID, and then shows the real appointment — including a
correction when the claimed date is wrong.

Local run and server update (`git pull` + restart): [DEPLOY.md](DEPLOY.md).
Screen recording of the golden chat: [demo.webm](demo.webm).

## Run

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# create a .env next to app.py with GEMINI_API_KEY=... and SESSION_SECRET=...
.venv/bin/uvicorn app:app --reload
```

http://127.0.0.1:8000 — chat is home; staff pages are in the top nav.
The header shows **Gemini פעיל** when the key is set. Without it the chat
asks for `GEMINI_API_KEY` and will not extract a name.

```
.venv/bin/python check_chat.py
```

runs the required submission scenarios on a throwaway database. It injects
a local NLU double and does not call Gemini.

Optional CLI: `.venv/bin/python main.py` (arrow-key menus on a real terminal).

Edit `config.yaml` for business name, hours, and services.

## Structure

```
README.md              - this file
DEPLOY.md              - local run, server update, PR review
demo.webm              - screen recording of the golden chat
app.py                 - web: pages, forms, chat HTTP
chat.py                - conversation state; no SQL, no HTTP
nlu.py                 - Gemini extract/phrase (required for live chat)
check_chat.py          - submission scenarios (local NLU, no network)
scripts/pr_review.py   - Gemini review of a PR diff
.github/workflows/     - Gemini PR code review
templates/             - Hebrew RTL pages
static/app.css         - one stylesheet
static/fonts/          - Noto Sans Hebrew (UI and receipt PDFs)
main.py                - CLI: the only file that prints or reads input
Features/              - business rules; no SQL, no print(), no input()
DB/db_adapter.py       - every SQL statement in the project
DB/schema.sql          - table definitions
DB/seed_demo.py        - Rotem Miron + 19.01.2027 19:00 demo row
config.yaml            - business identity, hours, services
receipts_out/          - generated receipt PDFs (not committed)
```

Each of `customers`, `leads`, `appointments`, `receipts` lives in its own
SQLite file under `DB/`. There are no foreign keys between them; `Features`
checks cross-references in Python. The `.db` files are gitignored; missing
tables are created on first run.

## Known limits

- Booking is check-then-insert, not atomic — fine for one user, needs a
transaction if this becomes multi-user.
- Lead-to-customer conversion writes to two separate database files and
cannot be a single transaction; see the comment in `Features/leads.py`.
- Converted leads have no national ID until staff fills it in; the chat
will refuse to verify them and will not reveal an appointment.
- The course demo appointment at 19.01.2027 19:00 is inserted directly;
`book()` would reject it because Sunday hours close at 17:00. The week
grid grows to show that block; empty cells after closing stay unbookable.
- Receipt PDFs use Noto Sans Hebrew when
`static/fonts/NotoSansHebrew-Regular.ttf` is present; Latin lines stay on
Helvetica. A mixed Hebrew+Latin string in one cell may miss glyphs.
