/* Mock data for the Phase-0 clickable mock.
   Names, numbers and page references are ILLUSTRATIVE ONLY — they mirror the
   shape of the real objects (docs/03_domain_model.md) so the screens can be
   exercised, not real extracted values. */

const OUTLINE = [
  { n: 0,  title: 'Identity & document control',            m11: 'Title page / front matter', pct: 100, err: 0, warn: 0, inc: 0 },
  { n: 1,  title: 'Study summary',                          m11: '1 Protocol Summary',                 pct: 82,  err: 0, warn: 1, inc: 2 },
  { n: 2,  title: 'Scientific justification',               m11: '2 Introduction',                     pct: 71,  err: 0, warn: 0, inc: 3 },
  { n: 3,  title: 'Questions & outcomes',                   m11: '3 Trial Objectives & Estimands',     pct: 90,  err: 1, warn: 1, inc: 1 },
  { n: 4,  title: 'Design & participant paths',             m11: '4 Trial Design',                     pct: 76,  err: 0, warn: 2, inc: 2 },
  { n: 5,  title: 'Participant selection',                  m11: '5 Trial Population',                 pct: 88,  err: 0, warn: 1, inc: 1 },
  { n: 6,  title: 'Treatments & concomitant care',          m11: '6 Trial Intervention',               pct: 64,  err: 2, warn: 1, inc: 4 },
  { n: 7,  title: 'Discontinuation & continued observation',m11: '7 Participant Discontinuation',      pct: 58,  err: 0, warn: 0, inc: 3 },
  { n: 8,  title: 'Assessments & procedures',               m11: '8 Trial Assessments & Procedures',   pct: 69,  err: 1, warn: 0, inc: 5 },
  { n: 9,  title: 'Safety events & reporting',              m11: '9 Adverse Events, SAEs …',           pct: 47,  err: 0, warn: 1, inc: 6 },
  { n: 10, title: 'Statistical specification',              m11: '10 Statistical Considerations',      pct: 62,  err: 1, warn: 2, inc: 4 },
  { n: 11, title: 'Oversight & conduct',                    m11: '11 Trial Oversight',                 pct: 35,  err: 0, warn: 0, inc: 7 },
  { n: 12, title: 'Supporting material',                    m11: '12 Appendix: Supporting Details',    pct: 20,  err: 0, warn: 0, inc: 4 },
  { n: 13, title: 'Terminology',                            m11: '13 Appendix: Glossary',              pct: 55,  err: 0, warn: 0, inc: 2 },
  { n: 14, title: 'References',                             m11: '14 Appendix: References',            pct: 40,  err: 0, warn: 1, inc: 3 },
];

const WORKS = [
  { id: 'W-102', title: 'SRK-201 · Phase 2b · anti-OX40L in moderate-to-severe AD', kind: 'Protocol', version: 'v0.3 (draft)', pct: 64, blocking: 5, updated: '2 min ago', owner: 'Ben Altman', starter: 'Temtokibart P2b (TRP-2b-01)', collaborators: ['BA', 'MK', 'JR'] },
  { id: 'W-103', title: 'SRK-201 · SAP v0.1', kind: 'SAP', version: 'v0.1 (draft) · depends on protocol v0.3', pct: 31, blocking: 2, updated: '1 h ago', owner: 'Maya K.', starter: '—', collaborators: ['MK'] },
  { id: 'W-098', title: 'SRK-115 · Phase 2a · topical PDE4 in mild AD', kind: 'Protocol', version: 'v1.0 · Amendment 1 draft', pct: 97, blocking: 0, updated: 'yesterday', owner: 'Ben Altman', starter: 'GSK P2b (GSK-AD-2b)', collaborators: ['BA', 'JR'] },
];

const STUDIES = [
  { id: 'S-01', name: 'Temtokibart P2b (TRP-2b-01)', drug: 'temtokibart', moa: 'anti-IL-22R', phase: '2b', n: 480, source: 'protocol PDF (text layer)', ocr: null, endpoints: ['EASI CFB', 'EASI-75', 'EASI-90', 'IGA 0/1', 'NRS ≥4'], tps: ['W4', 'W8', 'W12', 'W16'], status: 'accepted' },
  { id: 'S-02', name: 'Temtokibart P2a', drug: 'temtokibart', moa: 'anti-IL-22R', phase: '2a', n: 120, source: 'protocol PDF (text layer)', ocr: null, endpoints: ['EASI CFB', 'EASI-75', 'IGA 0/1'], tps: ['W8', 'W16'], status: 'accepted' },
  { id: 'S-03', name: 'GSK P2b (GSK-AD-2b)', drug: 'GSK-x', moa: 'undisclosed', phase: '2b', n: 360, source: 'protocol PDF (text layer)', ocr: null, endpoints: ['EASI %CFB', 'EASI-75', 'IGA 0/1', 'NRS ≥4'], tps: ['W12', 'W16'], status: 'accepted' },
  { id: 'S-04', name: 'Lebrikizumab P2b (ADvocate-precursor)', drug: 'lebrikizumab', moa: 'anti-IL-13', phase: '2b', n: 280, source: 'protocol PDF (image-only → OCR 0.83)', ocr: 0.83, endpoints: ['EASI %CFB', 'EASI-50/75/90', 'IGA 0/1', 'NRS ≥4'], tps: ['W16'], status: 'needs_review' },
  { id: 'S-05', name: 'Upadacitinib Measure Up 1 (FDA review)', drug: 'upadacitinib', moa: 'JAK1', phase: '3', n: 847, source: 'FDA review PDF', ocr: null, endpoints: ['EASI-75', 'EASI-90', 'IGA 0/1', 'NRS ≥4'], tps: ['W2', 'W4', 'W16'], status: 'accepted' },
  { id: 'S-06', name: 'Abrocitinib JADE MONO-1 (FDA review)', drug: 'abrocitinib', moa: 'JAK1', phase: '3', n: 387, source: 'FDA review PDF', ocr: null, endpoints: ['EASI-75', 'EASI-90', 'IGA 0/1', 'NRS ≥4'], tps: ['W2', 'W4', 'W12'], status: 'accepted' },
  { id: 'S-07', name: 'Dupilumab SOLO 1 (FDA review)', drug: 'dupilumab', moa: 'anti-IL-4Rα', phase: '3', n: 671, source: 'FDA review PDF', ocr: null, endpoints: ['EASI-75', 'EASI-90', 'IGA 0/1', 'NRS ≥4'], tps: ['W16'], status: 'accepted' },
];

/* Historical analysis records: illustrative EASI-75 @ W16 placebo/active rates. */
const HIST = [
  { study: 'S-05', arm: 'placebo', endpoint: 'EASI-75', tp: 'W16', pct: 16.3, n: 281, page: 41, comparable: true },
  { study: 'S-05', arm: 'upadacitinib 30 mg', endpoint: 'EASI-75', tp: 'W16', pct: 79.7, n: 285, page: 41, comparable: true, jak: true },
  { study: 'S-06', arm: 'placebo', endpoint: 'EASI-75', tp: 'W12', pct: 11.8, n: 77, page: 55, comparable: false, why: 'W12, not W16' },
  { study: 'S-06', arm: 'abrocitinib 200 mg', endpoint: 'EASI-75', tp: 'W12', pct: 62.7, n: 154, page: 55, comparable: false, why: 'W12, not W16', jak: true },
  { study: 'S-07', arm: 'placebo', endpoint: 'EASI-75', tp: 'W16', pct: 14.7, n: 224, page: 28, comparable: true },
  { study: 'S-07', arm: 'dupilumab 300 mg q2w', endpoint: 'EASI-75', tp: 'W16', pct: 51.3, n: 224, page: 28, comparable: true },
  { study: 'S-04', arm: 'placebo', endpoint: 'EASI-75', tp: 'W16', pct: 24.3, n: 52, page: 12, comparable: false, why: 'TCS background; OCR 0.83 unreviewed' },
  { study: 'S-01', arm: 'placebo', endpoint: 'EASI-75', tp: 'W16', pct: 21.0, n: 96, page: 88, comparable: true },
];

const FINDINGS = [
  { id: 'F-1', rule: 'R04', sev: 'error', sec: 8, msg: 'EASI assessment at Week 16 is required by primary endpoint EP-01 but is not scheduled in the SoA (encounter V8 missing EASI).', targets: ['EP-01', 'SoA'] },
  { id: 'F-2', rule: 'R11', sev: 'error', sec: 6, msg: 'Rescue rule RL-03 has no linked rescue event; estimand EST-01 strategy for rescue cannot be checked.', targets: ['RL-03', 'EST-01'] },
  { id: 'F-3', rule: 'R14', sev: 'warning', sec: 10, msg: 'Candidate: analysis AN-04 is labelled "sensitivity" but changes the estimand (hypothetical → treatment policy). Should be "supplementary" per E9(R1).', targets: ['AN-04'], candidate: true },
  { id: 'F-4', rule: 'R12', sev: 'error', sec: 3, msg: 'Estimand EST-02 lacks a population-level summary.', targets: ['EST-02'] },
  { id: 'F-5', rule: 'R03', sev: 'error', sec: 10, msg: 'Claim in §10.11 "approximately 400 participants" ≠ model sample_size.total = 480.', targets: ['AN-01'] },
  { id: 'F-6', rule: 'R07', sev: 'error', sec: 6, msg: 'Regimen RG-02 says "every 2 weeks" but dose calendar lists Weeks 0, 2, 4, 8, 12 (Week 6 missing).', targets: ['RG-02'] },
  { id: 'F-7', rule: 'R22', sev: 'warning', sec: 1, msg: 'Model value endpoints.EP-01.time_reference changed (W12 → W16) at rev 41; 3 blocks in §1, §3, §10 need review.', targets: ['EP-01'] },
  { id: 'F-8', rule: 'R05', sev: 'warning', sec: 4, msg: 'Source conflict: protocol v3.0 (p. 34) says 3 cohorts; amendment 2 (p. 5) says 4 cohorts. Not reconciled.', targets: ['periods'], candidate: true },
];

const QUESTIONS = [
  { id: 'Q1', q: 'Dose regimen for SRK-201: dose level(s), route and interval', type: 'value', covers: ['D-06 regimen', 'D-07 loading dose', 'D-14 dose calendar'], pkg: 'Intervention', status: 'open' },
  { id: 'Q2', q: 'Is a loading dose used?', type: 'choice', opts: ['Yes', 'No'], covers: ['D-07'], pkg: 'Intervention', status: 'merged→Q1' },
  { id: 'Q3', q: 'Half-life / washout period for exclusion of prior biologics (weeks or 5 half-lives)', type: 'value', covers: ['D-21 washout', 'D-22 prior biologic exclusion'], pkg: 'Population', status: 'open' },
  { id: 'Q4', q: 'Does SRK-201 carry a known class risk that needs a specific safety assessment (e.g. conjunctivitis for IL-13, infections for JAK)?', type: 'free', covers: ['D-31 safety assessments', 'D-33 AESI list'], pkg: 'Safety', status: 'open' },
  { id: 'Q5', q: 'Which anti-drug antibody sampling schedule applies?', type: 'choice', opts: ['Same as temtokibart (W0, W4, W16, EOS)', 'Custom'], covers: ['D-28 immunogenicity'], pkg: 'Assessments', status: 'derived from Q1 (SC biologic ⇒ ADA required)' },
  { id: 'Q6', q: 'Rescue therapy policy: permitted after which visit, and how is rescue handled in the primary estimand?', type: 'choice', opts: ['Permitted after W4; composite (rescue = non-responder)', 'Permitted after W4; treatment policy', 'Custom'], covers: ['D-11 rescue policy', 'D-12 rescue event', 'D-13 estimand strategy'], pkg: 'Estimands (study-specific — re-asked)', status: 'inherited — confirm' },
  { id: 'Q7', q: 'Target population age range', type: 'value', covers: ['D-01 age'], pkg: 'Population (study-specific — re-asked)', status: 'inherited — confirm', prefill: '18–75 (from starter)' },
];

const USERS = [
  { name: 'Ben Altman', email: 'ben@sarika.com', role: 'admin', last: '2 min ago', works: 3 },
  { name: 'Maya K.', email: 'maya@sarika.com', role: 'statistician', last: '1 h ago', works: 2 },
  { name: 'Jon R.', email: 'jon.r@gmail.com', role: 'author', last: 'yesterday', works: 2 },
  { name: 'Priya S.', email: 'priya@sarika.com', role: 'reviewer', last: '3 d ago', works: 1 },
];

const PROVIDERS = [
  { id: 'P-1', vendor: 'OpenAI', label: 'OpenAI (org key)', base: 'https://api.openai.com/v1', key: 'sk-…9f2a', enabled: true, classes: ['public', 'confidential'], seeded: true,
    models: [ { id: 'gpt-6-astra', caps: ['structured', 'streaming', '1M ctx'], enabled: true, defaults: ['split', 'adapt', 'group', 'claims', 'review', 'ask'] },
              { id: 'gpt-5-codex', caps: ['structured', 'streaming'], enabled: false, defaults: [] } ] },
  { id: 'P-2', vendor: 'xAI', label: 'xAI Grok', base: 'https://api.x.ai/v1', key: 'xai-…c41d', enabled: true, classes: ['public'],
    models: [ { id: 'grok-4', caps: ['streaming', 'structured?'], enabled: true, defaults: [] } ] },
  { id: 'P-3', vendor: 'OpenAI-compatible', label: 'Muse (self-hosted)', base: 'https://muse.internal/v1', key: '— not set', enabled: false, classes: [], models: [] },
];

const CRITERIA_SIMILAR = [
  { study: 'Temtokibart P2b', text: 'EASI ≥ 16 at screening and baseline', diff: [], page: 44 },
  { study: 'Dupilumab SOLO 1', text: 'EASI ≥ 16 at screening and baseline', diff: [], page: 19 },
  { study: 'Upadacitinib Measure Up 1', text: 'EASI ≥ 16 at baseline', diff: ['dropped "screening and"'], page: 22 },
  { study: 'Lebrikizumab P2b', text: 'EASI ≥ 12 at screening and baseline', diff: ['threshold ≥ 12'], page: 15, ocr: 0.83 },
  { study: 'GSK P2b', text: 'EASI ≥ 16 and IGA ≥ 3 at baseline', diff: ['added IGA ≥ 3', 'dropped "screening"'], page: 31 },
  { study: 'Abrocitinib JADE MONO-1', text: 'EASI ≥ 16 at baseline, BSA ≥ 10%', diff: ['added BSA ≥ 10%', 'dropped "screening"'], page: 27 },
];
