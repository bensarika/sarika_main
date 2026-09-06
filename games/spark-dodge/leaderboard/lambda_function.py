"""Sarika Pong leaderboard: reads and writes a single JSON object in S3.

GET  -> {"scores": [{"name": str, "score": int, "at": iso8601}, ...]}
POST {"name": str, "score": int} -> the updated list.

Exposed through a public Lambda Function URL, so it is deliberately small:
scores are trust-based, entries are capped, and writes are conditional on the
object's ETag so concurrent submissions cannot silently drop each other.
"""

import json
import os
import re
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

BUCKET = os.environ["LEADERBOARD_BUCKET"]
KEY = os.environ.get("LEADERBOARD_KEY", "leaderboard.json")
MAX_ENTRIES = 20
MAX_SCORE = 100000
NAME_RE = re.compile(r"[^\w .'-]", re.UNICODE)

s3 = boto3.client("s3")

HEADERS = {"content-type": "application/json", "cache-control": "no-store"}


def _load():
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=KEY)
    except ClientError as err:
        if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return [], None
        raise
    return json.loads(obj["Body"].read()).get("scores", []), obj["ETag"]


def _clean_name(raw):
    name = NAME_RE.sub("", str(raw or "").strip())[:16].strip()
    return name or "Guest"


def _reply(status, body):
    return {"statusCode": status, "headers": HEADERS, "body": json.dumps(body)}


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": HEADERS, "body": ""}

    if method == "GET":
        scores, _ = _load()
        return _reply(200, {"scores": scores})

    if method != "POST":
        return _reply(405, {"error": "method not allowed"})

    try:
        payload = json.loads(event.get("body") or "{}")
        score = int(payload.get("score"))
    except (ValueError, TypeError):
        return _reply(400, {"error": "score must be an integer"})

    if score < 1 or score > MAX_SCORE:
        return _reply(400, {"error": "score out of range"})

    entry = {
        "name": _clean_name(payload.get("name")),
        "score": score,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    # Retry the read-modify-write when another submission wins the race.
    for _ in range(4):
        scores, etag = _load()
        merged = sorted(scores + [entry], key=lambda s: -s["score"])[:MAX_ENTRIES]
        condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
        try:
            s3.put_object(
                Bucket=BUCKET,
                Key=KEY,
                Body=json.dumps({"scores": merged}).encode(),
                ContentType="application/json",
                **condition,
            )
        except ClientError as err:
            if err.response["Error"]["Code"] in ("PreconditionFailed", "ConditionalRequestConflict"):
                continue
            raise
        return _reply(200, {"scores": merged})

    return _reply(503, {"error": "leaderboard busy, try again"})
