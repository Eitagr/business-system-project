# Conversation state for identity verification. No SQL, no HTTP.
# Appointment details are only formatted after verify_id succeeds.

from Features import appointments, customers
from Features.customers import CustomerError

import nlu as default_nlu

IDLE = "idle"
CLARIFY = "clarify"
ASK_ID = "ask_id"
BLOCKED = "blocked"
MAX_ATTEMPTS = 3

YES = {"כן", "כן.", "יו", "נכון", "yes", "y"}
NO = {"לא", "לא.", "ביטול", "no", "n"}


def new_session() -> dict:
    return {
        "state": IDLE,
        "candidate_ids": [],
        "claimed_date": None,
        "attempts": 0,
    }


def _clean(text) -> str:
    return (text or "").strip()


def _digits(text) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _he_date(iso) -> str:
    year, month, day = iso.split("-")
    return f"{day}.{month}.{year}"


def _he_time(stamp) -> str:
    return stamp[11:16]


def _day(stamp) -> str:
    return stamp[:10]


def _template_reply(name, claimed_date, rows) -> str:
    if not rows:
        return f"מצאתי אותך, {name}. אין תור פתוח במערכת."

    lines = []
    for row in rows:
        lines.append(f"{_he_date(_day(row['starts_at']))} בשעה {_he_time(row['starts_at'])}")
    actual = "; ".join(lines)
    claimed = _he_date(claimed_date) if claimed_date else None
    actual_days = {_day(row["starts_at"]) for row in rows}

    if claimed_date and claimed_date not in actual_days:
        return (
            f"מצאתי אותך! שימו לב: התור שלך בפועל הוא ב-{actual} "
            f"(ולא ב-{claimed} כפי שציינת)."
        )
    if claimed_date:
        return f"מצאתי אותך! התור מאושר ל-{actual}."
    return f"מצאתי אותך! התור שלך ב-{actual}."


def _ask_which(candidates) -> str:
    names = " או ".join(row["name"] for row in candidates)
    if len(candidates) == 1:
        return f"קוראים לך {candidates[0]['name']}?"
    return f"מצאתי כמה לקוחות בשם הזה: {names}. מי מביניהם?"


def _pick(candidates, text):
    folded = _clean(text)
    if folded.lower() in YES or folded in YES:
        return candidates[0] if len(candidates) == 1 else None
    if folded.isdigit():
        index = int(folded) - 1
        if 0 <= index < len(candidates):
            return candidates[index]
        return None
    matches = [row for row in candidates if folded in row["name"]]
    if len(matches) == 1:
        return matches[0]
    lasts = []
    for row in candidates:
        parts = row["name"].split()
        if parts and folded == parts[-1]:
            lasts.append(row)
    if len(lasts) == 1:
        return lasts[0]
    return None


def _load_candidates(db, ids):
    rows = []
    for cid in ids:
        try:
            row = customers.require(db, cid, active_only=True)
        except CustomerError:
            continue
        rows.append({"id": row["id"], "name": row["name"]})
    return rows


def _verified_reply(db, customer, claimed_date, nlu) -> str:
    rows = [dict(row) for row in appointments.open_for_customer(db, customer["id"])]
    facts = {
        "name": customer["name"],
        "claimed_date": claimed_date,
        "appointments": [
            {"starts_at": row["starts_at"], "service": row.get("service")} for row in rows
        ],
    }
    styled = None
    try:
        styled = nlu.phrase(facts)
    except Exception:
        styled = None
    if styled:
        return styled.strip()
    return _template_reply(customer["name"], claimed_date, rows)


def kind_of(reply, session) -> str:
    """UI hint only. Never 'verified' unless handle already passed verify_id."""
    state = (session or {}).get("state")
    if state == BLOCKED:
        return "blocked"
    if state == CLARIFY:
        return "clarify"
    if state == ASK_ID:
        return "ask_id"
    if (reply or "").startswith("מצאתי אותך"):
        return "verified"
    return "plain"


def handle(db, session, text, nlu=None):
    nlu = nlu or default_nlu
    session = dict(session or new_session())
    session.setdefault("state", IDLE)
    session.setdefault("candidate_ids", [])
    session.setdefault("claimed_date", None)
    session.setdefault("attempts", 0)
    text = _clean(text)

    if session["state"] == BLOCKED:
        return "לא הצלחנו לאמת את הזהות. לחצו על «שיחה חדשה» כדי להתחיל מחדש.", session

    if not text:
        return "כתבו הודעה קצרה — שם ותאריך התור אם יש.", session

    if session["state"] == IDLE:
        extracted = nlu.extract(text) or {}
        name = (extracted.get("name") or "").strip()
        session["claimed_date"] = extracted.get("claimed_date")
        if not name:
            return "לא הצלחתי להבין את השם. נסו למשל: קוראים לי רותם ויש לי תור בתאריך 18.01.2027", session
        found = customers.find_by_name(db, name)
        if not found:
            return "לא מצאתי לקוח בשם הזה.", session
        session["candidate_ids"] = [row["id"] for row in found]
        session["state"] = CLARIFY
        session["attempts"] = 0
        return _ask_which(found), session

    if session["state"] == CLARIFY:
        if _clean(text).lower() in NO or _clean(text) in NO:
            session = new_session()
            return "בסדר. אם תרצו, כתבו שוב את השם.", session
        candidates = _load_candidates(db, session["candidate_ids"])
        if not candidates:
            session = new_session()
            return "לא מצאתי לקוח בשם הזה.", session
        chosen = _pick(candidates, text)
        if chosen is None:
            return _ask_which(candidates), session
        session["candidate_ids"] = [chosen["id"]]
        session["attempts"] = 0
        if not customers.has_national_id(db, chosen["id"]):
            session = new_session()
            return "לא ניתן לאמת את הלקוח הזה. פנו לצוות.", session
        session["state"] = ASK_ID
        return "מה תעודת הזהות שלך? (לצורך אימות בלבד)", session

    if session["state"] == ASK_ID:
        candidates = _load_candidates(db, session["candidate_ids"])
        if len(candidates) != 1:
            session = new_session()
            return "לא מצאתי לקוח בשם הזה.", session
        customer = customers.require(db, candidates[0]["id"], active_only=True)
        if not customers.has_national_id(db, customer["id"]):
            session = new_session()
            return "לא ניתן לאמת את הלקוח הזה. פנו לצוות.", session
        offered = _digits(text)
        if len(offered) != 9:
            return "צריך תשע ספרות של תעודת זהות.", session
        if customers.verify_id(db, customer["id"], offered):
            reply = _verified_reply(db, customer, session.get("claimed_date"), nlu)
            session = new_session()
            return reply, session
        session["attempts"] = int(session.get("attempts") or 0) + 1
        left = MAX_ATTEMPTS - session["attempts"]
        if left <= 0:
            session = {"state": BLOCKED, "candidate_ids": [], "claimed_date": None, "attempts": MAX_ATTEMPTS}
            return "המספר לא תואם. לא הצלחנו לאמת את הזהות, והשיחה נעצרת כאן.", session
        return f"המספר לא תואם. נותרו {left} ניסיונות.", session

    session = new_session()
    return "כתבו הודעה קצרה — שם ותאריך התור אם יש.", session
