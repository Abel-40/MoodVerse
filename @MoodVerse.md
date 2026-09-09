# @MoodVerse

## Workspace Structure

Entries marked `(generated)` are deterministic pipeline outputs. They are git-ignored and
rebuilt from the committed sources and scripts, never committed.

```text
MoodVerse/
├── bible related/                            # read-only source input
│   ├── AKJV.xml                              # public domain
│   └── cross_references.txt                  # OpenBible, CC-BY
├── quran related/                            # read-only source input
│   ├── Complete_Quran_data.csv
│   ├── Only TCEC cols.csv
│   ├── ELQV-main/                            # upstream ELQV, CC0
│   │   ├── ELQV.csv
│   │   ├── ELQVv2.csv
│   │   ├── LICENSE
│   │   └── README.md
│   └── quran-semantic-annotation-corpus-master/   # upstream QSAC, CC BY 4.0
│       ├── CITATION.cff
│       ├── LICENSE
│       ├── README.md
│       └── data/
│           ├── README.md
│           ├── qsac-dataset.csv
│           └── qsac-ontology.json
├── processed/
│   ├── build_unified_corpus.py               # Phase 0 pipeline (deterministic, rerunnable)
│   ├── osis_book_map.py                      # explicit OSIS -> AKJV book-name table
│   ├── unified_scripture_corpus.jsonl        # (generated) the unified corpus
│   ├── cross_reference_graph.json            # (generated) Bible cross-reference graph
│   ├── qsac_ontology.json                    # verbatim copy of the QSAC ontology
│   ├── source_catalog.json                   # per-source metadata and relationships
│   ├── source_mapping_report.json            # how sources were joined
│   ├── validation_report.json                # validation output for the latest run
│   ├── unresolved_records.json               # everything Phase 0 could not resolve
│   ├── clarification.md                      # Phase 0 processing report
│   ├── _legacy/                              # previous pipeline version, kept for audit
│   └── enrichment/                           # Phase 1: AI-assisted curation
│       ├── README.md                         # start here for Phase 1
│       ├── PHASE1B_REPORT.md
│       ├── mv_common.py                      # shared paths and helpers
│       ├── build_label_inventory.py          # source labels -> inventory
│       ├── build_ledger.py / ledger_rules.py # label ledger and mapping rules
│       ├── build_priors.py                   # deterministic priors
│       ├── build_enrichment.py               # enrichment assembly
│       ├── annotate.py                       # Gemini annotation driver
│       ├── curation.py                       # curation decisions
│       ├── validate.py                       # validation and parity checks
│       ├── build_docs.py                     # taxonomy/mapping doc generation
│       ├── annotation/
│       │   ├── prompts/                      # (private) annotation prompts, git-ignored
│       │   └── runs/                         # (generated) model run logs, git-ignored
│       ├── curation/
│       │   ├── enrichment.jsonl              # (generated)
│       │   ├── decisions.jsonl               # (generated)
│       │   └── review_queue.json
│       ├── mappings/
│       │   ├── label_inventory.json
│       │   ├── mapping_rules.md
│       │   ├── quarantine.json
│       │   └── source_label_ledger.json
│       ├── priors/
│       │   ├── deterministic_priors.jsonl    # (generated)
│       │   └── prior_rules.md
│       ├── schemas/gemini_response.schema.json
│       ├── taxonomy/                         # taxonomy.json, definitions.md, CHANGELOG.md
│       ├── tests/test_phase1.py
│       └── validation/                       # agreement, coverage, parity reports
├── PHASE1A_DESIGN.md
├── about_project.md
├── architecture.md
├── implementation_phases.md
└── @MoodVerse.md
```

## Phase status

**Phase 0 (scripture discovery -> extraction -> normalization -> unification): complete.**
Read `processed/clarification.md` first - it documents what was extracted, how sources were
mapped, what was deliberately left uninterpreted, and what Phase 1 should do next.

**Phase 1 (AI-assisted curation, suitability scoring, enrichment): in progress.**
See `processed/enrichment/README.md` and `processed/enrichment/PHASE1B_REPORT.md`.

The `bible related/` and `quran related/` directories are **read-only source inputs**. The
pipeline hashes them before and after every run and fails if any digest changes. Only the
eight files the pipeline reads are hashed; unused upstream extras (helper scripts, cover
image) were pruned from the vendored copies. Their `LICENSE`, `CITATION.cff` and `README.md`
are retained verbatim to satisfy attribution.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
Copy-Item processed\enrichment\.env.example processed\enrichment\.env
# then put your Gemini API key in processed\enrichment\.env
```

`processed/enrichment/annotation/prompts/` is not in the repository. Phase 1 annotation
requires those prompt files to be supplied separately.

## Rebuilding

```powershell
python processed/build_unified_corpus.py
```

Same inputs + same pipeline version produce byte-identical outputs.
