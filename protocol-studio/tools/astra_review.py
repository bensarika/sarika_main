#!/usr/bin/env python3
"""Ask OpenAI GPT-6 Astra to review design docs or a diff (ADR-009).

Usage:
    OPENAI_API_KEY=... python tools/astra_review.py docs/*.md --spec reference/AD_protocol_builder_spec.md \
        --out docs/reviews/$(date +%Y%m%d)-astra-docs.md
    git diff main...HEAD | python tools/astra_review.py --diff - --out review.md

Why this exists: the user asked for Astra to be the coding/reasoning agent.
Running it through a script (rather than pasting into a chat UI) makes every
review reproducible — the prompt version, the inputs and the token usage are
recorded at the top of the output file.

Only the standard library is used so the script works before the API
package's dependencies are installed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROMPT_VERSION = "review-v1"
DEFAULT_MODEL = "gpt-6-astra"
API_URL = "https://api.openai.com/v1/responses"

SYSTEM_PROMPT = """You are a principal engineer and regulatory-writing domain expert reviewing
design material for a clinical-trial protocol/SAP authoring application that
will be used for regulatory submissions.

Review rigorously and concretely. Organise your answer as:
1. Blocking issues (would cause rework or regulatory risk if built as designed)
2. Gaps versus the requirements and the specification supplied
3. Simplifications (what can be removed or deferred without losing value)
4. Specific suggestions (numbered, each with the file/section it targets)
5. Questions the team should ask the customer

Be specific: quote the passage you are reacting to. Do not restate the docs.
Prefer fewer, higher-value points over exhaustive lists."""


def read_inputs(paths: list[str]) -> str:
    parts = []
    for p in paths:
        text = Path(p).read_text()
        parts.append(f"\n\n===== FILE: {p} =====\n{text}")
    return "".join(parts)


def call_astra(model: str, system: str, user: str, max_output_tokens: int) -> dict:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY is not set")
    body = {
        "model": model,
        "instructions": system,
        "input": user,
        "max_output_tokens": max_output_tokens,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:  # surface the API's own message
        sys.exit(f"OpenAI API error {e.code}: {e.read().decode()[:2000]}")


def extract_text(response: dict) -> str:
    out = []
    for item in response.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    out.append(c["text"])
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="design docs to review")
    ap.add_argument("--spec", action="append", default=[], help="specification/requirements files for context")
    ap.add_argument("--diff", help="path to a diff to review, or '-' for stdin")
    ap.add_argument("--focus", default="", help="extra instructions, e.g. 'focus on the validation engine'")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-output-tokens", type=int, default=6000)
    ap.add_argument("--out", required=True, help="markdown file to write the review to")
    args = ap.parse_args()

    user_parts = []
    if args.spec:
        user_parts.append("REQUIREMENTS / SPECIFICATION (context, do not review these):" + read_inputs(args.spec))
    if args.files:
        user_parts.append("DESIGN MATERIAL TO REVIEW:" + read_inputs(args.files))
    if args.diff:
        diff = sys.stdin.read() if args.diff == "-" else Path(args.diff).read_text()
        user_parts.append("CODE DIFF TO REVIEW:\n```diff\n" + diff + "\n```")
    if args.focus:
        user_parts.append("ADDITIONAL FOCUS: " + args.focus)
    if not user_parts:
        sys.exit("nothing to review")

    response = call_astra(args.model, SYSTEM_PROMPT, "\n\n".join(user_parts), args.max_output_tokens)
    usage = response.get("usage", {})
    header = (
        f"# Astra review\n\n"
        f"- date: {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}\n"
        f"- model: {response.get('model', args.model)}\n"
        f"- prompt_version: {PROMPT_VERSION}\n"
        f"- inputs: {', '.join(args.files)}{' + diff' if args.diff else ''}\n"
        f"- spec context: {', '.join(args.spec) or 'none'}\n"
        f"- usage: {json.dumps(usage)}\n\n---\n\n"
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + extract_text(response))
    print(f"wrote {out} ({usage.get('output_tokens', '?')} output tokens)")


if __name__ == "__main__":
    main()
