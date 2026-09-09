# MoodVerse — System Architecture

## 1. Architectural principle

MoodVerse separates input modality, AI analysis, scripture retrieval, persistence, and presentation.

This allows V1 text input to evolve into V2 voice input without rewriting the recommendation engine.

## 2. High-level architecture

```text
┌──────────────────────┐
│   React Native App   │
│                      │
│ Reflection           │
│ Scripture selection  │
│ Results              │
│ History              │
│ Sharing              │
└──────────┬───────────┘
           │ HTTPS
           ▼
┌──────────────────────┐
│      FastAPI API     │
│                      │
│ Auth                 │
│ Reflection API       │
│ Recommendation API   │
│ History / Feedback   │
└──────────┬───────────┘
           │
     ┌─────┼──────────────┐
     ▼     ▼              ▼
  Gemini Retrieval   Application
  Service Engine     Services
     │      │             │
     └──────┼─────────────┘
            ▼
┌────────────────────────────┐
│ Supabase PostgreSQL        │
│                            │
│ Scriptures                 │
│ Metadata / Enrichment      │
│ Embeddings / pgvector      │
│ Users / Profiles           │
│ Reflections                │
│ Feedback                   │
└────────────────────────────┘
```

## 3. Data layers

### Layer A — Source-faithful corpus

Currently under `data/processed/`, built by `pipeline/phase0/`.

This is the completed Phase 0 baseline.

It preserves source information and provenance and is not the final recommendation dataset.

### Layer B — MoodVerse enrichment

A separate layer adds controlled semantics such as:

- primary emotion;
- secondary emotions;
- intensity;
- themes;
- intent;
- situations;
- spiritual purpose;
- standalone usefulness;
- context dependency;
- curation status;
- confidence;
- provenance.

This must not overwrite Layer A.

### Layer C — Application database

The production database will contain application structures such as:

```text
users
profiles
scriptures
emotions
themes
intents
scripture_emotions
scripture_themes
scripture_intents
scripture_enrichment
reflections
reflection_results
feedback
```

The exact schema is finalized during implementation.

## 4. Hybrid retrieval

Retrieval combines:

1. semantic/vector similarity;
2. religion filtering;
3. emotion compatibility;
4. theme compatibility;
5. intent compatibility;
6. intensity compatibility;
7. standalone usefulness;
8. context suitability;
9. curation status.

Weights must be configurable and experimentally evaluated rather than treated as permanent truth.

The Phase 0 cross-reference vote count is NOT an emotional relevance score.

## 5. pgvector

pgvector is mandatory for V1.

Scriptures receive embeddings during ingestion/indexing.

A user's reflection is embedded at request time.

Vector similarity finds semantically related passages while metadata filters and curation rules prevent vector similarity from being the only decision mechanism.

## 6. AI boundary: build time versus runtime

MoodVerse uses AI in two places that must not be confused. They differ in who
runs them, when, and what they are allowed to touch.

### 6.1 Build time — corpus enrichment (no paid API)

Enrichment and curation of the scripture corpus is **offline work performed by
the development agent** and committed to the repository as versioned structured
files under `data/processed/enrichment/`.

- **No paid inference API is called to enrich the corpus.** Gemini is not
  required, and is not used, for ingestion, enrichment or curation.
- Annotations are written to `annotation/runs/<run_id>/responses.jsonl` by
  `pipeline/phase1/agent_annotate.py` and replayed by `build_enrichment.py`,
  which stays a pure function of its inputs.
- Every authored annotation passes the same validator the paid path would have
  faced (`annotate.validate_response`): evidence spans must be verbatim
  substrings of the Phase 0 text, free text may not contain a scripture
  reference, and malformed records are rejected rather than repaired.
- Provenance is explicit. Each record carries the annotator, the run id and the
  method `agent_authored`; `build_enrichment.py` records the field-level method
  as `ai_generated` or `ai_reviewed`.
- `pipeline/phase1/annotate.py` remains in the tree as the Gemini path. It is
  optional, unused by default, and produces the identical output format.

The consequence: **a clone with no API key can rebuild the entire corpus and
enrichment layer.** Nothing about ingestion depends on a billing relationship.

### 6.2 Runtime — reflection analysis (Gemini free tier)

Gemini is reserved for serving a user request. Its only job is to turn a
person's free-text reflection into validated structured data.

- The runtime provider uses a **Gemini free-tier API key**, held server-side.
- It analyses the reflection into emotions, themes and intent. It does not
  select, rank, retrieve, quote or produce scripture.
- Scripture always comes from the curated corpus in the database. The runtime
  model never generates it, and never sees a request to.

Use an abstraction so the provider can be swapped without touching application
architecture:

```text
AIProvider
└── GeminiProvider          # runtime reflection analysis, free tier
```

The application depends on the interface, not on Gemini-specific code. Changing
provider must mean adding a class, not editing the retrieval engine, the schema
or the API surface.

Gemini may analyze a reflection into validated structured data such as:

```json
{
  "primary_emotion": "discouragement",
  "secondary_emotions": ["exhaustion", "frustration"],
  "intensity": 0.82,
  "themes": ["hope", "perseverance", "trust"],
  "intent": "comfort"
}
```

The final schema must be validated with Pydantic.

Gemini must not:

- invent scripture;
- invent references;
- rewrite scripture;
- become the source of scripture text;
- silently override curated/source data.

## 7. V1 text flow

```text
React Native
  ↓
Reflection text
  ↓
FastAPI validation
  ↓
Gemini structured analysis
  ↓
Validated analysis object
  ↓
Reflection embedding
  ↓
Hybrid retrieval
  ↓
Ranking
  ↓
Selected scripture
  ↓
Reflection persistence
  ↓
React Native result
```

## 8. V2 voice architecture

V2 should add voice through an adapter:

```text
React Native microphone
       ↓
Audio
       ↓
Cartesia speech-to-text
       ↓
Canonical reflection text
       ↓
Existing V1 pipeline
```

Use an abstraction such as:

```text
SpeechToTextProvider
└── CartesiaSpeechToTextProvider
```

Cartesia-specific code must remain isolated.

The rest of the system should receive only canonical text and should not care whether it came from typing or speech.

Do not make Cartesia a V1 dependency.

## 9. Database/security boundary

React Native communicates with FastAPI.

React Native must not:

- call Gemini directly;
- expose Gemini API keys;
- connect directly to PostgreSQL;
- expose Supabase service-role credentials.

Privileged credentials remain server-side.

## 10. Sharing

The backend returns structured scripture information.

React Native renders the 9:16 card locally and handles:

- export;
- saving;
- OS sharing;
- social sharing.

## 11. Background processing

Background processing may be used for:

- corpus enrichment;
- bulk embedding generation;
- ingestion;
- re-indexing.

Do not introduce Celery/Redis unless the workload requires it.

## 12. Extensibility

The architecture should leave room for:

- voice;
- multiple AI providers;
- multiple speech-to-text providers;
- personalization;
- recommendation feedback;
- improved ranking;
- additional translations;
- analytics/evaluation.

Do not implement future features merely to make the architecture look sophisticated.

## 13. Non-negotiable rules

1. Scripture text comes from trusted corpus data.
2. Gemini is not scripture source-of-truth.
2a. Corpus enrichment requires no paid API. It is produced offline by the
    development agent and committed as versioned files.
2b. Gemini is a runtime concern only, on a free-tier key, for reflection
    analysis. It never generates, selects or quotes scripture.
3. Phase 0 source data remains immutable.
4. Enrichment is separate from source data.
5. Retrieval is separate from AI analysis.
6. Input modality is separate from recommendation logic.
7. Provider-specific implementations are isolated.
8. Religion is an explicit retrieval constraint.
9. pgvector is required in V1.
10. Voice is V2.
11. Cartesia is a V2 speech-to-text provider.
12. Curated semantic data must retain provenance.
13. Important transformations must be reproducible.
