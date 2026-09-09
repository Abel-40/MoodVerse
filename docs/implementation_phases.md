# MoodVerse — Implementation Phases

Phase 0 is complete.

The remaining work is intentionally divided into **four phases**.

Do not skip phases or silently begin the next phase.

---
**Phase 1 status: the pipeline is complete and passing; the corpus is not yet
annotated.** All 14 validation checks and 18 tests pass, and the annotation
harness is in place and producing records. What remains is annotation volume and
one open decision on the confidence ceiling - see the note at the end of Phase 1.
# Phase 1 — Scripture Curation and Enrichment

## Goal

Turn the Phase 0 source-faithful corpus into a carefully curated MoodVerse reflection corpus.

This phase comes before embeddings, PostgreSQL, FastAPI runtime, and React Native.

## Work

### Taxonomy

Define controlled vocabularies for:

- primary emotions;
- secondary emotions;
- intensity;
- themes;
- reflection intents;
- situations;
- spiritual purposes;
- context dependency.

The taxonomy must work across Bible and Quran and must not simply copy a single source dataset.

### Source mappings

Create reversible mappings from source-specific labels into MoodVerse categories.

Preserve:

- original source;
- original label;
- mapped label;
- confidence;
- rationale;
- mapping method.

### Enrichment

Create a separate enrichment layer supporting:

- emotions;
- themes;
- intent;
- situations;
- spiritual purpose;
- emotional relevance;
- standalone usefulness;
- context dependency;
- misleading-if-isolated;
- suitability scores;
- curation status;
- confidence;
- provenance.

### Curation

Distinguish at minimum:

```text
INCLUDE
INCLUDE_WITH_CONTEXT
EXCLUDE_FROM_DEFAULT_RECOMMENDATIONS
REVIEW_REQUIRED
```

Do not assume a meaningful verse is automatically a good standalone emotional recommendation.

### AI assistance

**Corpus enrichment requires no paid API and must not call one.**

Annotation is performed offline by the development agent and committed as
versioned structured files under `data/processed/enrichment/`. Gemini is neither
required nor used for ingestion, enrichment or curation. It is a runtime concern
only - see `backend.md`.

`pipeline/phase1/agent_annotate.py` writes annotations in the same run format
`annotate.py` produces, so `build_enrichment.py` replays either unchanged. The
Gemini path remains in the tree, optional and unused by default.

Whichever path produces an annotation, the annotator cannot:

- rewrite scripture;
- invent scripture;
- invent references;
- replace source text;
- silently overwrite source information;
- decide a curation status - a deterministic cascade does that.

Every annotation is validated by `annotate.validate_response`. Evidence spans
must be verbatim substrings of the Phase 0 text, free-text fields may not carry
a scripture reference, and a malformed record is rejected, never repaired.

### Cross references

Use cross references primarily for contextual understanding, not as emotional relevance scores.

### Bible/Quran balance

The Quran has richer existing semantic annotations than the Bible. Annotation quantity must not automatically create better recommendations for Quran.

## Expected structure

```text
data/processed/enrichment/
├── taxonomy/
├── mappings/
├── priors/
├── annotation/
│   ├── prompts/        (private, not in the repository)
│   └── runs/           versioned annotation runs
├── curation/
└── validation/

pipeline/phase1/        the scripts that produce all of the above
```

The exact structure may be refined during implementation.

## Exit criteria

- taxonomy defined;
- mappings are reversible;
- enrichment schema validated;
- curation rules implemented;
- enrichment generated;
- provenance preserved;
- validation passes;
- Phase 0 files remain unchanged.

Then HARD STOP.

## Open decision: the confidence ceiling

`build_enrichment.confidence_band` awards a record 0.60 confidence only when two
independent annotation passes exist, or when an expert-tier source corroborates
`expressed_affect` (which only Quran records can have, via ELQV). A single pass
otherwise yields 0.40 when corroborated by priors or source labels, and 0.20 when
not.

`curation.py` gate 4 requires confidence >= 0.60 for `INCLUDE`, and gate 1
rejects anything below 0.40 outright.

Therefore **one annotation pass can never produce an `INCLUDE` record.** It can
reach `INCLUDE_WITH_CONTEXT` at 0.40, and Bible records with no priors and no
source labels sit at 0.20 and cannot earn any automatic status at all.

This is the design working as written - default deny - not a defect. Resolving it
is a policy decision, and the options are:

1. run a genuinely independent second annotation pass;
2. add a human review step that promotes records to `human_reviewed`;
3. change what a single pass is worth in `confidence_band`.

Option 3 is the cheapest and the most dangerous: it lowers the evidentiary bar
for everything at once. Do not take it without deciding deliberately.

---

# Phase 2 — Backend, Database, Embeddings and Retrieval Foundation

## Goal

Create the backend and database foundation and make the curated corpus searchable.

The application structure does not currently exist.

Create it gradually.

Recommended high-level structure:

```text
MoodVerse/
├── data/
│   ├── raw/
│   └── processed/
├── pipeline/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   └── main.py
│   ├── tests/
│   ├── alembic/
│   ├── pyproject.toml
│   └── .env.example
├── frontend/
├── design/
└── docs/
```

Use:

- Python;
- FastAPI;
- Pydantic v2;
- SQLAlchemy 2.x;
- Alembic;
- Supabase PostgreSQL;
- pgvector.

## Database

Implement the schema needed for:

- users/profile;
- scriptures;
- emotions;
- themes;
- intents;
- scripture enrichment;
- reflection logs;
- feedback.

## Embeddings

Generate embeddings for curated scripture records and store them with pgvector.

Generate a reflection embedding at request time.

Make the embedding model/provider configurable.

## Retrieval

Implement:

- religion filtering;
- vector similarity;
- metadata filtering;
- curation filtering;
- explainable ranking.

## Testing

Test:

- database relationships;
- ingestion idempotency;
- vector retrieval;
- metadata filters;
- religion filters;
- ranking;
- invalid data.

## Exit criteria

The backend can connect to the database, query curated scriptures, perform vector search, apply metadata constraints, and return ranked candidates.

Then HARD STOP.

---

# Phase 3 — AI Runtime, API and React Native Application

## Goal

Connect the complete V1 product.

## Backend AI runtime

Implement:

```text
Reflection
   ↓
Gemini structured analysis
   ↓
Pydantic validation
   ↓
Embedding
   ↓
Hybrid retrieval
   ↓
Ranking
   ↓
Selected scripture
```

Use:

```text
AIProvider
└── GeminiProvider
```

## API

Implement appropriate V1 endpoints, including concepts such as:

```text
POST /api/v1/reflections/analyze
POST /api/v1/recommendations
GET  /api/v1/scriptures/{id}
GET  /api/v1/reflections/history
POST /api/v1/reflections/{id}/feedback
```

Exact endpoint design may be improved during implementation.

## Persistence

Store:

- original reflection;
- scripture tradition;
- analysis;
- selected scripture;
- retrieval information;
- timestamp;
- feedback.

## Authentication

Implement secure authentication and protected resources.



## Sharing

Render the scripture card locally in React Native and provide device sharing/export.

## Exit criteria

A user can:

1. open the app;
2. select Bible or Quran;
3. write a reflection;
4. submit it;
5. receive a curated scripture;
6. view the result;
7. see history;
8. provide feedback;
9. create/share the visual scripture card.

Then HARD STOP.

---

# Phase 4 — V2 Voice and Future Expansion

Phase 4 begins only after V1 is stable.

## Voice

Implement:

```text
React Native microphone
    ↓
Audio
    ↓
Cartesia speech-to-text
    ↓
Canonical text
    ↓
Existing V1 analysis/retrieval pipeline
```

Use:

```text
SpeechToTextProvider
└── CartesiaSpeechToTextProvider
```

The recommendation system must remain independent of the speech provider.

## Possible future expansion

Only implement these when explicitly approved:

- voice input improvements;
- personalization;
- improved ranking;
- richer feedback;
- reflection insights;
- notifications/reminders;
- advanced AI assistant;
- analytics/evaluation.

Do not allow V2 to become uncontrolled feature expansion.

---

# Execution Protocol

Every phase follows:

## 1. REVIEW

Inspect:

- existing files;
- previous phase outputs;
- dependencies;
- current repository state.

## 2. PLAN

Report:

- files to create;
- files to modify;
- files that must remain untouched;
- implementation order;
- risks.

## 3. IMPLEMENT

Implement only the approved phase.

Do not jump ahead.

## 4. VERIFY

Run:

- tests;
- validation;
- data integrity checks;
- important output checks.

Verify that previous-phase outputs remain intact.

## 5. REPORT

Report:

- what changed;
- files created;
- files modified;
- validation results;
- known limitations.

## 6. HARD STOP

Wait for explicit authorization.

Valid phase commands are:

```text
Phase 1 — Scripture Curation and Enrichment
Phase 2 — Backend, Database, Embeddings and Retrieval Foundation
Phase 3 — AI Runtime, API and React Native Application
Phase 4 — V2 Voice and Future Expansion
```

If the user has not explicitly authorized the next phase, do not implement it.
