# @MoodVerse

Code lives under `pipeline/`, data under `data/`, documentation under `docs/`.
Entries marked `(generated)` are deterministic outputs: git-ignored, rebuilt from
the committed sources and scripts, never committed.

```text
MoodVerse/
├── data/
│   ├── raw/                                  # read-only source inputs
│   │   ├── bible/
│   │   │   ├── AKJV.xml
│   │   │   └── cross_references.txt
│   │   └── quran/
│   │       ├── Complete_Quran_data.csv
│   │       ├── only_tcec_cols.csv
│   │       ├── elqv/{ELQV.csv, ELQVv2.csv}
│   │       └── qsac/{qsac-dataset.csv, qsac-ontology.json}
│   └── processed/
│       ├── unified_scripture_corpus.jsonl    # (generated) the unified corpus
│       ├── cross_reference_graph.json        # (generated) cross-reference graph
│       ├── qsac_ontology.json                # verbatim copy of the QSAC ontology
│       ├── source_catalog.json               # per-source metadata and digests
│       ├── source_mapping_report.json        # how sources were joined
│       ├── validation_report.json            # Phase 0 validation
│       ├── unresolved_records.json           # what Phase 0 could not resolve
│       ├── clarification.md                  # Phase 0 processing report
│       └── enrichment/                       # Phase 1 data
│           ├── README.md                     # start here for Phase 1
│           ├── taxonomy/                     # taxonomy.json is the source of truth
│           ├── mappings/                     # label inventory, ledger, quarantine
│           ├── priors/                       # (generated) deterministic priors
│           ├── annotation/
│           │   ├── prompts/                  # (private) not in the repository
│           │   └── runs/<run_id>/            # recorded annotation runs
│           ├── curation/                     # (generated) enrichment + decisions
│           └── validation/                   # validation, parity, coverage reports
├── pipeline/
│   ├── phase0/{build_unified_corpus.py, osis_book_map.py}
│   ├── phase1/
│   │   ├── mv_common.py                      # shared paths, IO, taxonomy access
│   │   ├── build_label_inventory.py          # source labels -> inventory
│   │   ├── build_ledger.py / ledger_rules.py # label ledger and mapping rules
│   │   ├── build_priors.py                   # deterministic priors
│   │   ├── agent_annotate.py                 # annotation, no API, no cost
│   │   ├── annotate.py                       # optional Gemini path, unused by default
│   │   ├── build_enrichment.py               # pure replay of recorded runs
│   │   ├── curation.py                       # the decision cascade
│   │   ├── validate.py                       # validation and parity checks
│   │   ├── build_docs.py                     # regenerates the generated docs
│   │   └── tests/test_phase1.py              # 18 tests
│   └── _legacy/                              # previous pipeline version, for audit
├── docs/
│   ├── about_project.md                      # product overview
│   ├── architecture.md                       # system architecture
│   ├── backend.md                            # backend contract (Phase 2 spec)
│   └── implementation_phases.md              # the phase protocol
├── .env                                      # (private) GEMINI_API_KEY
├── .env.example
└── @MoodVerse.md
```

## Phase status

**Phase 0 — complete.** 37,339 records (31,103 Bible, 6,236 Quran), 0 errors,
0 unresolved. Read `data/processed/clarification.md` first.

**Phase 1 — pipeline complete, annotation in progress.** 14/14 validation checks
and 18/18 tests pass. Annotation is performed offline by the development agent
and committed; no paid API is involved. See
`data/processed/enrichment/README.md`.

**Phase 2 — not started.** `docs/backend.md` is the binding specification.

## The AI boundary

Two distinct uses of AI, which must never be merged:

- **Build time — corpus enrichment.** Performed offline by the development
  agent, committed as versioned files. **No paid API. No cost.** A clone with no
  API key can rebuild everything.
- **Runtime — reflection analysis.** Gemini on a free-tier key, server-side
  only, turning a user's reflection into structured emotions, themes and intent.
  It never generates, selects or quotes scripture; scripture always comes from
  the curated corpus.

`data/raw/` is read-only. The pipeline hashes every file under it before and
after each run and fails if any digest changes.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
Copy-Item .env.example .env      # then add your Gemini key, for runtime only
```

## Rebuilding

```powershell
python pipeline/phase0/build_unified_corpus.py     # Phase 0
python pipeline/phase1/build_label_inventory.py    # Phase 1, in order
python pipeline/phase1/build_ledger.py
python pipeline/phase1/build_priors.py
python pipeline/phase1/build_enrichment.py --bootstrap
python pipeline/phase1/validate.py
python pipeline/phase1/tests/test_phase1.py
```

Same inputs plus the same pipeline version produce byte-identical outputs.
