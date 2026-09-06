# Submission scenarios for the course chatbot. Throwaway DB, no Gemini key.
# Not a unit-test suite.

import sys
import tempfile
from pathlib import Path

import yaml

import chat
from DB.db_adapter import Database
from DB.seed_demo import DEMO_START, ensure
from Features import appointments, leads
from nlu import fallback_extract

ROOT = Path(__file__).parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())

LEAKS = ("19:00", "19.01", "2027-01-19", "Consultation", "Follow-up", "Full session")


class ScriptedNLU:
    def extract(self, text):
        return fallback_extract(text)

    def phrase(self, facts):
        return None


def _talk(db, session, text, nlu):
    return chat.handle(db, session, text, nlu=nlu)


def _no_leak(replies, label):
    blob = "\n".join(replies)
    for token in LEAKS:
        if token in blob:
            raise AssertionError(f"{label}: leaked {token!r} before verify:\n{blob}")


def _run():
    nlu = ScriptedNLU()
    failures = []

    def check(name, fn):
        tmp = Path(tempfile.mkdtemp())
        db = Database(directory=tmp)
        try:
            ensure(db, CONFIG)
            fn(db)
            print(f"PASS  {name}")
        except Exception as exc:
            failures.append(name)
            print(f"FAIL  {name}: {exc}")
        finally:
            db.close()

    def unique_wrong_date(db):
        session = chat.new_session()
        r1, session = _talk(db, session, "קוראים לי רותם מירון ויש לי תור בתאריך 18.01.2027", nlu)
        r2, session = _talk(db, session, "כן", nlu)
        _no_leak([r1, r2], "unique before verify")
        if "מירון" not in r1:
            raise AssertionError(f"expected full-name confirm, got {r1!r}")
        if "זהות" not in r2:
            raise AssertionError(f"expected ID prompt, got {r2!r}")
        r3, session = _talk(db, session, "123456789", nlu)
        if "19.01.2027" not in r3 or "19:00" not in r3:
            raise AssertionError(f"expected corrected slot, got {r3!r}")
        if "18.01" not in r3:
            raise AssertionError(f"expected claimed-date correction, got {r3!r}")

    def ambiguous_name(db):
        session = chat.new_session()
        r1, session = _talk(db, session, "קוראים לי רותם ויש לי תור בתאריך 18.01.2027", nlu)
        _no_leak([r1], "ambiguous before verify")
        if "מירון" not in r1 or "לוי" not in r1:
            raise AssertionError(f"expected both Rotems, got {r1!r}")
        r2, session = _talk(db, session, "מירון", nlu)
        if "זהות" not in r2:
            raise AssertionError(f"expected ID prompt after choice, got {r2!r}")

    def wrong_id(db):
        session = chat.new_session()
        replies = []
        r, session = _talk(db, session, "קוראים לי רותם מירון", nlu)
        replies.append(r)
        r, session = _talk(db, session, "כן", nlu)
        replies.append(r)
        for _ in range(3):
            r, session = _talk(db, session, "000000000", nlu)
            replies.append(r)
        _no_leak(replies, "wrong id")
        if session["state"] != chat.BLOCKED:
            raise AssertionError(f"expected blocked, got {session['state']}")

    def no_open_appointment(db):
        session = chat.new_session()
        r1, session = _talk(db, session, "קוראים לי רותם לוי", nlu)
        r2, session = _talk(db, session, "כן", nlu)
        r3, session = _talk(db, session, "987654321", nlu)
        _no_leak([r1, r2], "no-open before verify")
        if "אין תור פתוח" not in r3:
            raise AssertionError(f"expected no open appointment, got {r3!r}")

    def unknown_name(db):
        session = chat.new_session()
        r1, session = _talk(db, session, "קוראים לי פלוני אלמוני ויש לי תור בתאריך 18.01.2027", nlu)
        _no_leak([r1], "unknown")
        if "לא מצאתי" not in r1:
            raise AssertionError(f"expected not found, got {r1!r}")

    def id_in_first_message(db):
        session = chat.new_session()
        r1, session = _talk(
            db,
            session,
            "קוראים לי רותם מירון, תעודת זהות 123456789, תור ב-18.01.2027",
            nlu,
        )
        r2, session = _talk(db, session, "כן", nlu)
        _no_leak([r1, r2], "id in first message")
        if "מירון" not in r1:
            raise AssertionError(f"expected name confirm, got {r1!r}")
        if "זהות" not in r2:
            raise AssertionError(f"expected ID prompt, got {r2!r}")
        if session["state"] != chat.ASK_ID:
            raise AssertionError(f"must not skip verify, state={session['state']}")
        r3, session = _talk(db, session, "123456789", nlu)
        if "19:00" not in r3:
            raise AssertionError(f"expected slot after explicit ID, got {r3!r}")

    def converted_without_id(db):
        lid = leads.add(db, "יעל בדיקה", "050-1212121")
        leads.convert(db, lid)
        session = chat.new_session()
        r1, session = _talk(db, session, "קוראים לי יעל בדיקה", nlu)
        r2, session = _talk(db, session, "כן", nlu)
        _no_leak([r1, r2], "no national id")
        if "לא ניתן לאמת" not in r2:
            raise AssertionError(f"expected refuse after clarify, got {r2!r}")
        if session["state"] != chat.IDLE:
            raise AssertionError(f"expected idle after refuse, got {session['state']}")

    check("1 unique name + wrong date", unique_wrong_date)
    check("2 ambiguous first name", ambiguous_name)
    check("3 wrong national id", wrong_id)
    check("4 customer with no open appointment", no_open_appointment)
    check("5 unknown name", unknown_name)
    check("7 national id in first message", id_in_first_message)
    check("8 converted lead without national id", converted_without_id)

    tmp = Path(tempfile.mkdtemp())
    db = Database(directory=tmp)
    try:
        ensure(db, CONFIG)
        stamp = appointments.stamp(DEMO_START)
        rows = [row for row in db.list_appointments() if row["starts_at"] == stamp]
        if not rows:
            failures.append("demo slot")
            print("FAIL  demo 19:00 row missing")
        else:
            print("PASS  demo 19:00 row")
        for entity, count in (
            ("customers", len(db.list_customers(active=None))),
            ("appointments", len(db.list_appointments())),
            ("leads", len(db.list_leads())),
            ("receipts", len(db.list_receipts())),
        ):
            if count < 5:
                failures.append(entity)
                print(f"FAIL  {entity} has {count} rows, need >= 5")
            else:
                print(f"PASS  {entity} {count} rows")
    finally:
        db.close()

    if failures:
        print(f"\n{len(failures)} failed.")
        sys.exit(1)
    print("\nAll scenarios passed.")


if __name__ == "__main__":
    _run()
