"""Source connections: where hosted FDA reviews / protocols / SAPs live.

S3: ``s3://bucket/prefix/`` checked with boto3 using the runtime's AWS
credentials (instance role in production; ``AWS_*`` env locally). Listing is
paged and capped; objects are returned with key, size, ETag and last-modified so
a sync can register them as SourceRecords without downloading.

Dropbox: a shared-folder link is validated by shape only. Reading it needs a
Dropbox app token, which is not configured; the connection is stored with
``status=not_configured`` so the UI can say exactly that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from protocol_studio.settings import settings

MAX_OBJECTS = 500
DOC_EXTENSIONS = (".pdf", ".md", ".markdown", ".txt", ".xlsx", ".docx", ".json")


@dataclass
class Check:
    status: str  # ok | error | not_configured
    message: str
    objects: list[dict[str, Any]] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


def parse_s3(uri: str) -> tuple[str, str]:
    u = urlparse(uri.strip())
    if u.scheme == "s3" and u.netloc:
        return u.netloc, u.path.lstrip("/")
    m = re.match(r"^https?://([^./]+)\.s3[.-][^/]*amazonaws\.com/(.*)$", uri.strip())
    if m:
        return m.group(1), m.group(2)
    raise ValueError("expected s3://bucket/prefix/ or an https S3 URL")


def check_s3(uri: str) -> Check:
    try:
        bucket, prefix = parse_s3(uri)
    except ValueError as e:
        return Check("error", str(e))
    try:
        s3 = boto3.client("s3", region_name=settings.aws_region)
        paginator = s3.get_paginator("list_objects_v2")
        objects: list[dict[str, Any]] = []
        total = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for o in page.get("Contents", []):
                total += 1
                key = str(o["Key"])
                if len(objects) < MAX_OBJECTS and key.lower().endswith(DOC_EXTENSIONS):
                    objects.append(
                        {
                            "key": key,
                            "name": key.rsplit("/", 1)[-1],
                            "size": int(o.get("Size", 0)),
                            "etag": str(o.get("ETag", "")).strip('"'),
                            "last_modified": o["LastModified"].isoformat() if o.get("LastModified") else None,
                            "uri": f"s3://{bucket}/{key}",
                        }
                    )
            if total >= MAX_OBJECTS * 4:
                break
    except NoCredentialsError:
        return Check("not_configured", "no AWS credentials available to this server")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "ClientError")
        return Check("error", f"S3 {code}: cannot list s3://{bucket}/{prefix}")
    except BotoCoreError as e:
        return Check("error", f"S3 client error: {e.__class__.__name__}")
    msg = f"{len(objects)} document(s) under s3://{bucket}/{prefix}" + (
        " (bucket prefix is empty)" if total == 0 else ""
    )
    return Check("ok", msg, objects, {"bucket": bucket, "prefix": prefix, "total_objects": total})


def check_dropbox(uri: str) -> Check:
    u = urlparse(uri.strip())
    if u.scheme not in ("http", "https") or not u.netloc.endswith("dropbox.com"):
        return Check("error", "expected a dropbox.com shared link")
    return Check(
        "not_configured",
        "link recorded; listing Dropbox folders needs a Dropbox app token configured by an administrator",
        detail={"host": u.netloc, "path": u.path},
    )


def check(kind: str, uri: str) -> Check:
    if kind == "s3":
        return check_s3(uri)
    if kind == "dropbox":
        return check_dropbox(uri)
    return Check("error", f"unknown connection kind {kind!r}")
