"""Evidence: the parsed-once study library and the master sheet per indication.

    schema.py       StudyRecord — the common canonical JSON for a parsed study (protocol / SAP /
                    FDA review). Every fact carries a Provenance (document, page/section, how it
                    was obtained). This is what makes re-use instantaneous: parse once, cite forever.
    master.py       Seeded records (reference/evidence/<indication>/*.json) + DB records → master
                    sheet rows, endpoint matrix, indication summaries.
    extract.py      Deterministic first-pass extraction from PDF / Markdown / Excel bytes:
                    identifiers, version labels, candidate primary-endpoint and eligibility
                    sentences with page numbers. Output is *candidate* content for human review,
                    never silently promoted to a StudyRecord.
    compare.py      Side-by-side comparisons: endpoint definitions, eligibility criteria (with
                    parsed age bounds and regional exceptions), results for one endpoint/timepoint.
    connections.py  Source connections: S3 bucket/prefix status + listing (boto3), Dropbox link
                    validation. Files from a connection are registered as SourceRecords.

Rules: nothing here invents a value. Seeded facts either quote a page of a
retrieved PDF, cite a registry, or are labelled synthetic. Results marked
``synthetic`` are planning fixtures and are flagged as such all the way to the UI.
"""
