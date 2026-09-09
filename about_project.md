# MoodVerse — Project Overview

## 1. What is MoodVerse?

MoodVerse is a spiritual reflection application that helps a person find a relevant Bible or Quran passage based on what they are emotionally experiencing.

A user describes their current emotional state in natural language. MoodVerse analyzes the reflection, identifies the emotional and spiritual context, and retrieves a carefully curated scripture passage appropriate for that situation.

The goal is not to build a generic chatbot that happens to quote scripture. The goal is to build a reliable scripture-recommendation system where:

- the user's words are understood semantically;
- scripture comes from verified source data rather than an LLM;
- scripture is curated for emotional and spiritual suitability;
- retrieval combines semantic similarity with structured metadata;
- the selected passage can be beautifully presented and shared;
- the architecture can later support voice input without rewriting the recommendation system.

## 2. Problem it solves

People experience emotions such as sadness, loneliness, anxiety, fear, discouragement, grief, anger, guilt, shame, confusion, uncertainty, exhaustion, frustration, disappointment, helplessness, joy, gratitude, hope, peace, and love.

They may want comfort, hope, encouragement, guidance, strength, patience, gratitude, worship, repentance, or wisdom, but finding an appropriate passage manually can be difficult.

Keyword search is also insufficient because a person's description may not use the same words as a relevant scripture.

## 3. Core product flow

```text
User reflection
      ↓
Emotion / theme / intent analysis
      ↓
Structured emotional representation
      ↓
Hybrid scripture retrieval
      ↓
Curated candidates
      ↓
Ranking
      ↓
Best scripture
      ↓
Beautiful presentation / sharing
```

Gemini must never be the source of scripture text.

## 4. Supported scripture

V1 supports:

- Holy Bible
- Holy Quran

The user explicitly selects the scripture tradition.

The completed Phase 0 corpus contains:

- Bible: 31,102 records
- Quran: 6,236 records
- Total: 37,338 records

Phase 0 also preserved source annotations, translations, Quran semantic annotations, Bible cross references, provenance, and validation information.

## 5. Critical product principle

A scripture can be theologically important or semantically related while still being a poor standalone emotional response.

MoodVerse must therefore distinguish:

- theological meaning;
- semantic relevance;
- emotional relevance;
- standalone usefulness;
- spiritual-purpose suitability;
- context dependency;
- suitability when isolated.

Do not recommend a passage simply because it matches a keyword or topic.

## 6. Technology

### Mobile frontend

- React Native
- TypeScript

The frontend is being developed collaboratively. The React Native client communicates with the FastAPI backend through HTTPS.

### Backend

- Python
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x
- Alembic

### Database

- Supabase PostgreSQL
- pgvector

pgvector is mandatory for V1 semantic retrieval.

### AI

- Google AI Studio / Gemini API

Gemini performs structured emotional/semantic analysis and may assist with corpus curation.

Gemini does not generate the scripture source text.

### Planned V2 voice

V2 will support voice input using Cartesia speech-to-text, using the available/free offering where appropriate.

Voice must be treated as an input modality:

```text
Voice
  ↓
Speech-to-text
  ↓
Canonical reflection text
  ↓
Existing analysis/retrieval pipeline
```

The recommendation system should not need to know whether the reflection came from typing or speech.

## 7. Sharing

MoodVerse should produce a beautiful 9:16 scripture presentation suitable for mobile stories and sharing.

The backend returns structured scripture data. React Native renders the visual card and handles local export/sharing.

## 8. Current repository state

The repository currently contains the original source/data workspace plus the completed Phase 0 output.

Existing important directories include:

```text
bible related/
quran related/
processed/
```

The application source structure has NOT yet been created.

Do not assume `backend/`, `frontend/`, `mobile/`, or `app/` already exists.

## 9. Data philosophy

Original source directories are read-only.

Phase 0 is the source-faithful baseline.

Future enrichment must be stored separately and must not overwrite:

```text
processed/unified_scripture_corpus.jsonl
```

Never silently:

- rewrite scripture;
- paraphrase scripture;
- invent references;
- merge translations;
- repair theological content using an LLM;
- convert source labels into MoodVerse labels without preserving the mapping.

Every transformation should be explainable and reproducible.

## 10. What MoodVerse is NOT

V1 is not intended to be:

- a general-purpose AI chatbot;
- a theological authority;
- an AI-generated scripture generator;
- a social network;
- a therapy or medical system;
- a replacement for religious leaders or personal study.

## 11. Engineering standard

MoodVerse should demonstrate:

- curated semantic data;
- controlled taxonomy;
- provenance;
- AI-assisted annotation;
- human-review readiness;
- hybrid retrieval;
- pgvector;
- structured Gemini output;
- explainable ranking;
- authentication;
- reflection history;
- feedback;
- testing;
- production security;
- provider abstraction;
- future voice support.

Build in dependency order and validate each phase before proceeding.
