# Gemini extraction and phrasing. Regex fallback is only for check_chat.py.

import json
import os
import re
from datetime import datetime

EXTRACT_PROMPT = """\
Extract a person name and an optional claimed appointment date from the user
message. Reply with ONLY a JSON object, no markdown, in this exact shape:
{"name": string or null, "claimed_date": "YYYY-MM-DD" or null}
name is the person's name as written (Hebrew or Latin), without extra words.
claimed_date is ISO if a calendar date is mentioned, else null.
User message:
"""

PHRASE_PROMPT = """\
Write a short Hebrew reply to a verified customer. Use only these facts.
If claimed_date differs from an actual appointment date, emphasize the correction.
Do not invent extra appointments, phone numbers, or IDs.
Facts JSON:
"""

_NAME = re.compile(r"קוראים לי\s+(.+?)(?:\s+ויש|\s+יש לי|$)", re.DOTALL)
_NAME_STOP = re.compile(
    r"(?:,|\s+תעודת|\s+ויש|\s+יש לי|"
    r"\s+\d{1,2}\.\d{1,2}\.\d{4}|\s+\d{4}-\d{2}-\d{2})"
)
_DATE_DOT = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_DATE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

MODEL = "gemini-3.6-flash"


class NLUError(Exception):
    """Gemini is required but missing, or the call failed."""


def configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def source() -> str:
    return "gemini" if configured() else "missing"


def _parse_date(text):
    match = _DATE_ISO.search(text)
    if match:
        try:
            return datetime.strptime(match.group(0), "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    match = _DATE_DOT.search(text)
    if not match:
        return None
    day, month, year = (int(match.group(i)) for i in (1, 2, 3))
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def fallback_extract(text) -> dict:
    text = (text or "").strip()
    name = None
    match = _NAME.search(text)
    if match:
        name = re.sub(r"\s+", " ", match.group(1)).strip(" ,.")
        stop = _NAME_STOP.search(name)
        if stop:
            name = name[: stop.start()].strip(" ,.")
        name = name or None
    return {"name": name, "claimed_date": _parse_date(text)}


def _load_json(raw) -> dict | None:
    if not raw:
        return None
    blob = raw.strip()
    match = _JSON_OBJECT.search(blob)
    if match:
        blob = match.group(0)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if isinstance(name, str):
        name = name.strip() or None
    else:
        name = None
    claimed = data.get("claimed_date")
    if claimed:
        try:
            claimed = datetime.strptime(str(claimed)[:10], "%Y-%m-%d").date().isoformat()
        except ValueError:
            claimed = _parse_date(str(claimed))
    else:
        claimed = None
    return {"name": name, "claimed_date": claimed}


def _model():
    if not configured():
        raise NLUError("GEMINI_API_KEY is missing")
    import google.generativeai as genai

    genai.configure(api_key=os.environ["GEMINI_API_KEY"].strip())
    return genai.GenerativeModel(MODEL)


def _gemini(prompt) -> str:
    response = _model().generate_content(
        prompt,
        generation_config={"temperature": 0},
    )
    text = (response.text or "").strip()
    if not text:
        raise NLUError("Gemini returned an empty reply")
    return text


def extract(text) -> dict:
    parsed = _load_json(_gemini(EXTRACT_PROMPT + (text or "")))
    if parsed is None:
        raise NLUError("Gemini did not return JSON")
    return parsed


def phrase(facts: dict) -> str:
    return _gemini(PHRASE_PROMPT + json.dumps(facts, ensure_ascii=False))
