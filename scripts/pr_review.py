# Post a Gemini review comment on the current pull request.
# Needs GEMINI_API_KEY, GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER, PR_DIFF_URL.

import json
import os
import sys
import urllib.error
import urllib.request

import google.generativeai as genai

MODEL = "gemini-3.6-flash"
MAX_DIFF = 24000

PROMPT = """\
Review this git diff for a student appointment chatbot (Hebrew).
Look for bugs, identity-verification leaks (appointment date/time/service
before a successful national-id check), and missing error handling.
Reply in short Hebrew bullets. If nothing serious, say so in one line.
Do not rewrite the patch.

Diff:
"""


def _env(name) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is missing")
    return value


def _get(url, accept, token) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "atlas-pr-review",
        },
    )
    with urllib.request.urlopen(req) as res:
        return res.read().decode()


def _post(url, body, token) -> None:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "atlas-pr-review",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as res:
        res.read()


def main() -> None:
    key = _env("GEMINI_API_KEY")
    token = _env("GITHUB_TOKEN")
    repo = _env("GITHUB_REPOSITORY")
    pr = _env("PR_NUMBER")
    diff_url = _env("PR_DIFF_URL")

    diff = _get(diff_url, "application/vnd.github.diff", token)
    if not diff.strip():
        print("No diff.")
        return
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + "\n… truncated …\n"

    genai.configure(api_key=key)
    model = genai.GenerativeModel(MODEL)
    review = (model.generate_content(PROMPT + diff).text or "").strip()
    if not review:
        sys.exit("Gemini returned an empty review")

    _post(
        f"https://api.github.com/repos/{repo}/issues/{pr}/comments",
        {"body": "## Gemini code review\n\n" + review},
        token,
    )
    print("Posted review comment.")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        sys.exit(f"GitHub HTTP {exc.code}: {exc.read().decode()[:500]}")
