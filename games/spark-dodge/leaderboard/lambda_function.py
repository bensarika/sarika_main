"""Sarika Pong leaderboard: reads and writes a single JSON object in S3.

GET  -> {"scores": [{"name": str, "score": int, "at": iso8601}, ...]}
POST {"score": int} with `Authorization: Bearer <Google ID token>` -> the updated list.

Exposed through a public Lambda Function URL. Submissions must carry a Google
ID token for this app's OAuth client from a @sarika.com account; the name on
the board comes from that account, one entry per person, top ten only. Writes
are conditional on the object's ETag so concurrent submissions cannot silently
drop each other.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

BUCKET = os.environ["LEADERBOARD_BUCKET"]
KEY = os.environ.get("LEADERBOARD_KEY", "leaderboard.json")
GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
ALLOWED_DOMAIN = os.environ.get("ALLOWED_DOMAIN", "sarika.com")
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo?"
MAX_ENTRIES = 10
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
    name = NAME_RE.sub("", str(raw or "").strip())[:24].strip()
    return name or "Sarikan"


def _reply(status, body):
    return {"statusCode": status, "headers": HEADERS, "body": json.dumps(body)}


def _verify_google(token):
    """Return the verified token claims, or None if Google rejects the token."""
    url = TOKENINFO_URL + urllib.parse.urlencode({"id_token": token})
    try:
        with urllib.request.urlopen(url, timeout=5) as res:
            claims = json.loads(res.read())
    except (urllib.error.URLError, ValueError):
        return None
    if claims.get("aud") != GOOGLE_CLIENT_ID or claims.get("email_verified") != "true":
        return None
    return claims


def _player(event):
    """Identify the signed-in Sarika player from the bearer token, or None."""
    auth = event.get("headers", {}).get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    claims = _verify_google(auth[7:].strip())
    if not claims:
        return None
    email = claims.get("email", "").lower()
    if claims.get("hd") != ALLOWED_DOMAIN or not email.endswith("@" + ALLOWED_DOMAIN):
        return None
    return {"email": email, "name": _clean_name(claims.get("name") or email.split("@")[0])}


def _merge(scores, entry):
    others = [s for s in scores if s.get("email") != entry["email"]]
    mine = [s for s in scores if s.get("email") == entry["email"]]
    if mine and mine[0]["score"] >= entry["score"]:
        entry = {**mine[0], "name": entry["name"]}
    return sorted(others + [entry], key=lambda s: -s["score"])[:MAX_ENTRIES]


def _public(scores):
    return [{"name": s["name"], "score": s["score"], "at": s.get("at")} for s in scores]


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": HEADERS, "body": ""}

    if method == "GET":
        scores, _ = _load()
        return _reply(200, {"scores": _public(scores)})

    if method != "POST":
        return _reply(405, {"error": "method not allowed"})

    player = _player(event)
    if not player:
        return _reply(401, {"error": "sign in with a @%s Google account" % ALLOWED_DOMAIN})

    try:
        score = int(json.loads(event.get("body") or "{}").get("score"))
    except (ValueError, TypeError):
        return _reply(400, {"error": "score must be an integer"})

    if score < 1 or score > MAX_SCORE:
        return _reply(400, {"error": "score out of range"})

    entry = {
        **player,
        "score": score,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    # Retry the read-modify-write when another submission wins the race.
    for _ in range(4):
        scores, etag = _load()
        merged = _merge(scores, entry)
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
        return _reply(200, {"scores": _public(merged)})

    return _reply(503, {"error": "leaderboard busy, try again"})
