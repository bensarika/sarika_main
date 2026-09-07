"""Evidence: master sheet from seeded records, upload → extract → review → study record, connections, comparisons."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pypdf import PdfWriter

from protocol_studio.evidence import compare, connections, extract, master
from protocol_studio.evidence.schema import Criterion, StudyRecord
from protocol_studio.starters import AD_ANTIBODY_ID
from tests.conftest import login_as

TEMTO_2A = Path("/home/ubuntu/attachments/5b4fdedc-fb91-4f3f-b56d-20593c53b10c/Temto_p2a_prot.pdf")

PROTOCOL_MD = b"""# Protocol XYZ-123 Version 2.0

ClinicalTrials.gov: NCT01234567

## Objectives and endpoints
Primary endpoint: Percent change in EASI score from baseline to Week 16.

## Inclusion criteria
1. Signed informed consent.
2. 18-70 years old (both included) at screening.
3. Diagnosis of AD for at least 1 year.
"""


def _pdf_with_text(lines: list[str]) -> bytes:
    """A one-page PDF with a real text layer (pypdf can write text via a content stream)."""
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    w = PdfWriter()
    page = w.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})}
    )
    body = "BT /F1 10 Tf 40 750 Td 14 TL " + " ".join(f"({ln}) Tj T*" for ln in lines) + " ET"
    stream = DecodedStreamObject()
    stream.set_data(body.encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(stream)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- seeded master sheet


def test_seeded_records_validate_and_master_rows(admin: TestClient) -> None:
    recs = master.seeded()
    ids = {r.id for r in recs}
    assert {
        "temtokibart-lp0145-1376",
        "temtokibart-lp0145-2240",
        "gsk1070806-219538",
        "synthetic-three-arm-example",
    } <= ids
    r = admin.get("/api/evidence/studies", params={"indication": "atopic-dermatitis"})
    assert r.status_code == 200
    rows = r.json()["rows"]
    by_id = {x["id"]: x for x in rows}
    # parsed records carry endpoint + timepoint; inventory-only records are registered with no endpoint
    t2a = by_id["temtokibart-lp0145-1376"]
    assert (
        t2a["tier"] == "parsed" and t2a["timepoint"] == "Week 16" and t2a["primary_transformation"] == "absolute_change"
    )
    assert t2a["provenance_status"] == "quoted"
    registered = [x for x in rows if x["tier"] == "registered"]
    assert registered and all(x["primary_endpoint"] is None for x in registered)
    # 17 retrieved protocols in the inventory; the 4 we parsed share ids with inventory entries
    assert len([x for x in rows if not x["synthetic"]]) == 17
    assert by_id["synthetic-three-arm-example"]["synthetic"] is True
    assert r.json()["results_source_linked"] is False  # only synthetic results exist so far


def test_indications_and_matrix(admin: TestClient) -> None:
    r = admin.get("/api/evidence/indications")
    assert r.status_code == 200
    ad = r.json()[0]
    assert ad["id"] == "atopic-dermatitis" and ad["studies"] == 17 and ad["parsed"] == 4 and ad["synthetic"] == 1
    m = admin.get("/api/evidence/matrix", params={"indication": "atopic-dermatitis"}).json()
    assert "EASI · percent_change" in m["columns"] and "EASI · absolute_change" in m["columns"]
    assert m["cells"]["gsk1070806-219538"]["EASI · percent_change"] == ["primary", "secondary"]


def test_study_detail_and_404(admin: TestClient) -> None:
    r = admin.get("/api/evidence/studies/temtokibart-lp0145-2240")
    assert r.status_code == 200
    d = r.json()
    assert d["tier"] == "parsed" and d["status"] == "approved"
    age = next(c for c in d["criteria"] if c["category"] == "age")
    assert age["min_age"] == 18 and age["max_age"] == 75 and age["provenance"]["page"] == 53
    assert admin.get("/api/evidence/studies/nope").status_code == 404
    # seeded records cannot be patched
    assert admin.patch("/api/evidence/studies/temtokibart-lp0145-2240", json={"status": "review"}).status_code == 404


# ----------------------------------------------------------------------------- extraction


def test_extract_markdown_finds_identifiers_endpoint_and_age() -> None:
    ex = extract.extract("protocol.md", PROTOCOL_MD)
    assert ex["media_type"] == "text/markdown" and ex["text_extractable"] is True
    assert ex["identifiers"]["nct"] == ["NCT01234567"] and "Version 2.0" in ex["identifiers"]["versions"]
    c = ex["primary_endpoint_candidates"][0]
    assert c["transformation"] == "percent_change" and c["timepoint_weeks"] == 16 and c["instrument"] == "EASI"
    e = ex["eligibility_candidates"][0]
    assert e["min_age"] == 18 and e["max_age"] == 70
    assert ex["sha256"] == hashlib.sha256(PROTOCOL_MD).hexdigest()


def test_extract_pdf_text_layer_and_page_numbers() -> None:
    pdf = _pdf_with_text(
        ["Protocol Amendment 3", "NCT09999999", "Primary endpoint: Change in EASI score from baseline to Week 12."]
    )
    ex = extract.extract("x.pdf", pdf)
    assert ex["pages"] == 1 and ex["text_extractable"] is False  # tiny text layer is below the 200-char floor
    assert ex["identifiers"]["nct"] == ["NCT09999999"]
    c = ex["primary_endpoint_candidates"][0]
    assert c["page"] == 1 and c["transformation"] == "absolute_change" and c["timepoint_weeks"] == 12


def test_extract_blank_pdf_is_flagged_not_guessed() -> None:
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    w.write(buf)
    ex = extract.extract("scan.pdf", buf.getvalue())
    assert ex["text_extractable"] is False and ex["primary_endpoint_candidates"] == []
    assert any("no machine-readable text" in wmsg for wmsg in ex["warnings"])


def test_extract_xlsx_table() -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["study", "endpoint", "week", "placebo", "active"])
    ws.append(["NCT00000001", "EASI-75", 16, 0.3, 0.6])
    buf = io.BytesIO()
    wb.save(buf)
    ex = extract.extract("results.xlsx", buf.getvalue())
    assert ex["table"]["header"] == ["study", "endpoint", "week", "placebo", "active"] and ex["table"]["row_count"] == 1
    assert ex["identifiers"]["nct"] == ["NCT00000001"]


@pytest.mark.skipif(not TEMTO_2A.exists(), reason="real protocol PDF not present")
def test_extract_real_temtokibart_protocol_matches_seed() -> None:
    ex = extract.extract(TEMTO_2A.name, TEMTO_2A.read_bytes())
    seed = next(r for r in master.seeded() if r.id == "temtokibart-lp0145-1376")
    assert ex["sha256"] == seed.documents[0].sha256 and ex["pages"] == 152 and ex["text_extractable"] is True
    # the sponsor document carries the EudraCT number, not the NCT id (which lives on the registry)
    assert ex["identifiers"]["eudract"] == ["2020-005541-16"] and "Version: 4.0" in ex["identifiers"]["versions"]
    prim = seed.primary()
    assert prim is not None
    cands = ex["primary_endpoint_candidates"]
    assert any(c["page"] == prim.provenance.page and c["transformation"] == "absolute_change" for c in cands), cands
    assert any(e.get("min_age") == 18 and e.get("max_age") == 64 for e in ex["eligibility_candidates"])


# ----------------------------------------------------------------------------- upload → review → study record


def test_upload_dedup_extract_draft_confirm(admin: TestClient) -> None:
    files = {"file": ("protocol.md", PROTOCOL_MD, "text/markdown")}
    r = admin.post("/api/evidence/sources", files=files, data={"indication": "atopic-dermatitis"})
    assert r.status_code == 201, r.text
    src = r.json()
    assert (
        src["sha256"] == hashlib.sha256(PROTOCOL_MD).hexdigest()
        and src["status"] == "uploaded"
        and src["reused"] is False
    )
    assert src["uri"] == ""  # local storage path is never exposed
    # same bytes again → same record, no duplicate
    r2 = admin.post("/api/evidence/sources", files=files)
    assert r2.status_code == 201 and r2.json()["id"] == src["id"] and r2.json()["reused"] is True
    assert len(admin.get("/api/evidence/sources").json()) == 1
    # draft before extraction → 409
    assert admin.get(f"/api/evidence/sources/{src['id']}/draft").status_code == 409
    r3 = admin.post(f"/api/evidence/sources/{src['id']}/extract")
    assert r3.status_code == 200, r3.text
    assert r3.json()["status"] == "review" and r3.json()["study_identifier"] == "NCT01234567"
    assert r3.json()["extraction"]["primary_endpoint_candidates"][0]["transformation"] == "percent_change"
    # extraction is cached
    assert admin.post(f"/api/evidence/sources/{src['id']}/extract").json()["reused"] is True
    d = admin.get(f"/api/evidence/sources/{src['id']}/draft").json()
    assert d["registry_ids"] == ["NCT01234567"] and d["endpoints"][0]["provenance"]["status"] == "unverified"
    assert d["criteria"][0]["min_age"] == 18 and d["criteria"][0]["max_age"] == 70
    # reviewer fills the blanks and confirms
    d["intervention"], d["title"], d["protocol_identifier"] = "xyzumab", "XYZumab Phase 2 · XYZ-123", "XYZ-123"
    d["endpoints"][0]["provenance"]["status"] = "quoted"
    r4 = admin.post(f"/api/evidence/sources/{src['id']}/study", json={"record": d})
    assert r4.status_code == 201, r4.text
    st = r4.json()
    assert st["id"] == "xyzumab-xyz-123" and st["tier"] == "user" and st["status"] == "review"
    # now on the master sheet and in the comparison
    rows = admin.get("/api/evidence/studies", params={"indication": "atopic-dermatitis"}).json()["rows"]
    row = next(x for x in rows if x["id"] == "xyzumab-xyz-123")
    assert row["primary_transformation"] == "percent_change" and row["tier"] == "user"
    assert admin.get(f"/api/evidence/sources/{src['id']}").json()["status"] == "canonical"
    # duplicate id rejected; approval is admin-only and works
    assert admin.post(f"/api/evidence/sources/{src['id']}/study", json={"record": d}).status_code == 409
    assert (
        admin.patch("/api/evidence/studies/xyzumab-xyz-123", json={"status": "approved"}).json()["status"] == "approved"
    )


def test_upload_rejects_unsupported_and_empty(admin: TestClient) -> None:
    assert (
        admin.post("/api/evidence/sources", files={"file": ("a.exe", b"MZ", "application/octet-stream")}).status_code
        == 415
    )
    assert admin.post("/api/evidence/sources", files={"file": ("a.md", b"", "text/markdown")}).status_code == 422
    assert (
        admin.post(
            "/api/evidence/sources", files={"file": ("a.md", b"x", "text/markdown")}, data={"document_type": "meme"}
        ).status_code
        == 422
    )


def test_link_source_registered_only(admin: TestClient) -> None:
    r = admin.post(
        "/api/evidence/sources/link",
        json={
            "url": "https://cdn.clinicaltrials.gov/large-docs/99/NCT05999799/Prot_002.pdf",
            "document_type": "protocol",
        },
    )
    assert r.status_code == 201 and r.json()["origin"] == "link" and r.json()["status"] == "registered"
    assert r.json()["media_type"] == "application/pdf"
    assert admin.post(f"/api/evidence/sources/{r.json()['id']}/extract").status_code == 422
    assert admin.post("/api/evidence/sources/link", json={"url": "ftp://x"}).status_code == 422


def test_source_visibility_acl(admin: TestClient) -> None:
    wid = admin.post("/api/works", json={"title": "SRK-201", "starter": AD_ANTIBODY_ID}).json()["id"]
    admin.post("/api/admin/users", json={"email": "viewer@sarika.com", "role": "author"})
    admin.post("/api/admin/users", json={"email": "outsider@sarika.com", "role": "author"})
    admin.put(f"/api/works/{wid}/permissions", json={"email": "viewer@sarika.com", "level": "view"})
    r = admin.post(
        "/api/evidence/sources",
        files={"file": ("study.md", b"# Study-only note", "text/markdown")},
        data={"visibility": "study", "work_id": wid},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    priv = admin.post(
        "/api/evidence/sources",
        files={"file": ("mine.md", b"# private", "text/markdown")},
        data={"visibility": "private"},
    ).json()["id"]
    login_as(admin, "viewer@sarika.com")
    seen = {s["id"] for s in admin.get("/api/evidence/sources").json()}
    assert sid in seen and priv not in seen
    assert admin.get(f"/api/evidence/sources/{priv}").status_code == 404
    # a viewer cannot attach study-scoped sources (needs edit)
    r = admin.post(
        "/api/evidence/sources",
        files={"file": ("v.md", b"# v", "text/markdown")},
        data={"visibility": "study", "work_id": wid},
    )
    assert r.status_code == 403
    login_as(admin, "outsider@sarika.com")
    assert sid not in {s["id"] for s in admin.get("/api/evidence/sources").json()}
    assert admin.get(f"/api/evidence/sources/{sid}").status_code == 404


# ----------------------------------------------------------------------------- connections


def test_connections_s3_and_dropbox(admin: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    objects = [
        {
            "key": "protocol-corpus/atopic-dermatitis/protocols/a.pdf",
            "name": "a.pdf",
            "size": 10,
            "etag": "e",
            "last_modified": None,
            "uri": "s3://b/protocol-corpus/atopic-dermatitis/protocols/a.pdf",
        },
    ]

    def fake_check_s3(uri: str) -> connections.Check:
        if "denied" in uri:
            return connections.Check("error", "S3 AccessDenied: cannot list")
        return connections.Check(
            "ok", "1 document(s)", objects, {"bucket": "b", "prefix": "protocol-corpus/", "total_objects": 1}
        )

    monkeypatch.setattr(connections, "check_s3", fake_check_s3)
    r = admin.get("/api/evidence/connections")
    assert r.status_code == 200 and r.json()["default_corpus"]["uri"].startswith("s3://sarika-main-fs/")
    r = admin.post("/api/evidence/connections", json={"kind": "s3", "uri": "s3://b/protocol-corpus/"})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "ok" and c["objects"][0]["name"] == "a.pdf" and c["detail"]["total_objects"] == 1
    s = admin.post(f"/api/evidence/connections/{c['id']}/sync").json()
    assert s["registered"] == 1
    assert admin.post(f"/api/evidence/connections/{c['id']}/sync").json()["registered"] == 0  # idempotent
    srcs = admin.get("/api/evidence/sources").json()
    assert srcs[0]["origin"] == "s3" and srcs[0]["uri"].startswith("s3://b/") and srcs[0]["status"] == "registered"
    bad = admin.post("/api/evidence/connections", json={"kind": "s3", "uri": "s3://denied/x/"}).json()
    assert bad["status"] == "error" and "AccessDenied" in bad["detail"]["message"]
    assert admin.post(f"/api/evidence/connections/{bad['id']}/sync").status_code == 409
    dbx = admin.post(
        "/api/evidence/connections", json={"kind": "dropbox", "uri": "https://www.dropbox.com/scl/fo/abc"}
    ).json()
    assert dbx["status"] == "not_configured"
    assert admin.post("/api/evidence/connections", json={"kind": "gdrive", "uri": "x"}).status_code == 422


def test_connection_scope_acl(admin: TestClient) -> None:
    admin.post("/api/admin/users", json={"email": "author@sarika.com", "role": "author"})
    login_as(admin, "author@sarika.com")
    r = admin.post("/api/evidence/connections", json={"kind": "dropbox", "uri": "https://www.dropbox.com/x"})
    assert r.status_code == 403  # workspace-wide connections are admin-only


def test_parse_s3_and_dropbox_shape() -> None:
    assert connections.parse_s3("s3://sarika-main-fs/protocol-corpus/") == ("sarika-main-fs", "protocol-corpus/")
    assert connections.parse_s3("https://sarika-main-fs.s3.us-east-2.amazonaws.com/x/y.pdf") == (
        "sarika-main-fs",
        "x/y.pdf",
    )
    with pytest.raises(ValueError):
        connections.parse_s3("gs://bucket/x")
    assert connections.check_dropbox("https://example.com/x").status == "error"
    assert connections.check("dropbox", "https://www.dropbox.com/scl/fo/abc").status == "not_configured"


# ----------------------------------------------------------------------------- comparisons


def test_compare_endpoints_flags_absolute_vs_percent(admin: TestClient) -> None:
    r = admin.get(
        "/api/evidence/compare/endpoints",
        params={"studies": "temtokibart-lp0145-1376,temtokibart-lp0145-2240,gsk1070806-219538,lebrikizumab-drm06-ad01"},
    )
    assert r.status_code == 200
    d = r.json()
    cols = {c["study_id"]: c for c in d["columns"]}
    assert cols["temtokibart-lp0145-1376"]["transformation"] == "absolute_change"
    assert cols["temtokibart-lp0145-2240"]["transformation"] == "percent_change"
    assert (
        cols["gsk1070806-219538"]["provenance"]["page"] == 24
        and cols["gsk1070806-219538"]["version_label"] == "Amendment 1"
    )
    kinds = {f["kind"] for f in d["flags"]}
    assert "transformation" in kinds and "provenance" in kinds  # lebrikizumab is registry-sourced
    assert "timepoint" not in kinds  # all Week 16
    # a registered-only study shows as missing rather than blank
    m = admin.get(
        "/api/evidence/compare/endpoints", params={"studies": "temtokibart-lp0145-1376,dupilumab-r668-ad-1526"}
    ).json()
    assert any(c.get("missing") for c in m["columns"])
    assert admin.get("/api/evidence/compare/endpoints", params={"studies": "nope"}).status_code == 404


def test_compare_eligibility_age(admin: TestClient) -> None:
    r = admin.get(
        "/api/evidence/compare/eligibility",
        params={"category": "age", "min_age": 18, "text": "Adults 18 years or older"},
    )
    assert r.status_code == 200
    d = r.json()
    rows = {x["study_id"]: x for x in d["rows"]}
    assert "synthetic-three-arm-example" not in rows
    t2b = rows["temtokibart-lp0145-2240"]
    assert t2b["difference"]["highlight"] is True and "Upper limit 75" in t2b["difference"]["text"]
    assert "Regional exceptions" in t2b["difference"]["text"] and t2b["provenance"]["page"] == 53
    gsk = rows["gsk1070806-219538"]
    assert gsk["difference"]["text"].startswith("Same minimum age") and gsk["difference"]["highlight"] is False
    assert d["note"]  # regional exceptions note surfaces
    # pure function: a different minimum age is flagged
    recs = [x for x in master.seeded() if x.id == "temtokibart-lp0145-1376"]
    ours = Criterion(id="o", kind="inclusion", category="age", text="12+", min_age=12)
    out = compare.compare_eligibility(recs, "age", ours)
    assert "Minimum age 18 (ours 12)" in out["rows"][0]["difference"]["text"]


def test_compare_results_synthetic_is_labelled_and_feeds_trial_lab(admin: TestClient) -> None:
    r = admin.get(
        "/api/evidence/compare/results",
        params={"instrument": "EASI", "transformation": "responder", "threshold": "75%", "week": 16},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["rows"] and d["all_synthetic"] is True
    assert {x["source_status"] for x in d["rows"]} == {"Simulation"}
    assert d["trial_lab"] == {
        "p_active": 0.6,
        "p_control": 0.3,
        "label": "EASI-75 · Week 16",
        "assumption_source": "synthetic",
    }
    # the hand-off plugs straight into the deterministic calculator
    tl = admin.post(
        "/api/trial-lab/sample-size",
        json={
            "variable_type": "binary",
            "p_active": d["trial_lab"]["p_active"],
            "p_control": d["trial_lab"]["p_control"],
            "alpha": 0.05,
            "power": 0.9,
        },
    )
    assert tl.status_code == 200, tl.text
    # no results at Week 12 → empty, no hand-off
    e = admin.get("/api/evidence/compare/results", params={"week": 12}).json()
    assert e["rows"] == [] and e["trial_lab"] is None and e["all_synthetic"] is False


def test_study_record_helpers() -> None:
    rec = next(r for r in master.seeded() if r.id == "gsk1070806-219538")
    assert isinstance(rec, StudyRecord) and rec.primary() is not None
    assert rec.endpoint("easi_pct_wk16") is not None and rec.endpoint("nope") is None
    assert rec.arm("placebo") is not None and rec.arm("x") is None
    assert master.slug("Dupilumab R668-AD-1021 / X") == "dupilumab-r668-ad-1021-x"
