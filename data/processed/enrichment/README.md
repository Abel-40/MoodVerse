# MoodVerse — Phase 1 enrichment layer

Converts the Phase 0 source-faithful corpus into a curated reflection corpus, **without ever
modifying Phase 0**. Every artefact here is additive; the join to the corpus happens at read time.

## Status

The deterministic half is complete and passing: 14/14 validation checks, 18/18 tests.

**Annotation requires no paid API.** It is performed offline by the development agent through
`agent_annotate.py` and committed as versioned files under `annotation/runs/`. Gemini is not used
for enrichment and is not needed to rebuild anything here; it is reserved for runtime reflection
analysis (see `docs/backend.md`).

Annotation is in progress. Un-annotated records are `REVIEW_REQUIRED` via `gate1.not_annotated`,
which is correct default-deny behaviour rather than a bug.

> **The confidence ceiling.** `confidence_band` awards 0.60 only for two independent passes, or
> for expert-tier corroboration of `expressed_affect` (Quran only, via ELQV). Gate 4 requires
> 0.60 for `INCLUDE`. So a single annotation pass can reach `INCLUDE_WITH_CONTEXT` but never
> `INCLUDE`, and Bible records with neither priors nor source labels sit at 0.20, below gate 1's
> floor. Resolving this is a policy decision - see the open decision in
> `docs/implementation_phases.md`.

## Running it

Run from the repository root. Phase 0 must have been built first
(`python pipeline/phase0/build_unified_corpus.py`).

```bash
python pipeline/phase1/build_label_inventory.py   # scan the corpus for every source label
python pipeline/phase1/build_ledger.py            # map those labels into the taxonomy
python pipeline/phase1/build_priors.py            # deterministic signals, all 37,339 records
python pipeline/phase1/build_docs.py              # regenerate definitions.md, mapping_rules.md

# annotation - no API key, no cost
python pipeline/phase1/agent_annotate.py status                      # what remains
python pipeline/phase1/agent_annotate.py worklist --limit 12 --out batch.json
#   ... author annotations against the worklist ...
python pipeline/phase1/agent_annotate.py ingest batch.jsonl          # validate and merge

python pipeline/phase1/build_enrichment.py --bootstrap  # assemble; accepts unreviewed ledger rows
python pipeline/phase1/validate.py                      # 14 checks + parity/coverage reports
python pipeline/phase1/tests/test_phase1.py             # 18 tests
```

`annotate.py` (the Gemini path) is retained and still works, but is optional and unused by
default. Both paths write the same run format and face the same validator.

`build_enrichment.py` is a **pure function** of (corpus + taxonomy + ledger + priors + recorded
runs + overrides). Re-running it makes zero API calls and produces byte-identical output — test 2
asserts this.

> **Note on the corpus size.** The Bible carries **31,103** verses, not the published AKJV's 31,102.
> 3 John 1:14 was split at its sentence boundary in this workspace's copy so the cross-reference
> file's versification resolves; no words were added, and the two verses concatenate to the
> original. See limitation 8 in `data/processed/clarification.md`.

## Layout

| Path | What it is |
| --- | --- |
| `taxonomy/taxonomy.json` | The single source of truth. 17 emotions, 47 themes, 17 intents, 30 situations, 18 scripture purposes. Hand-authored |
| `taxonomy/definitions.md` | Generated from the above. Do not hand-edit |
| `ledger_rules.py` | The declared mapping decisions. **The human-reviewable half** |
| `mappings/label_inventory.json` | Every distinct source label, scanned. Pure observation |
| `mappings/source_label_ledger.json` | 671 rows, one per (source, type, label) |
| `mappings/quarantine.json` | Low-frequency and anomalous labels, preserved not deleted |
| `priors/deterministic_priors.jsonl` | 18 rules over all 37,339 records. No AI |
| `annotation/prompts/` | The Gemini contract. Private, not in the repository |
| `annotation/runs/<run_id>/` | Recorded annotation runs, replayed by `build_enrichment.py` |
| `agent_annotate.py` | Agent annotation: worklist / ingest / status. No network calls |
| `annotate.py` | Optional Gemini path. The only file that makes network calls |
| `curation.py` | The decision cascade. Gemini never decides status |
| `curation/enrichment.jsonl` | The enrichment layer |
| `curation/decisions.jsonl` | Status + `rule_fired` per record, separable so the cascade can be re-tuned in seconds |
| `curation/overrides.jsonl` | Human overrides. **Append-only** |
| `validation/` | Validation, parity, coverage, agreement reports |

## The three rules that matter most

**1. Source emotion labels never reach `addressed_states`.**
`expressed_affect` is what the text *sounds like*; `addressed_states` is who it *helps*. They are
frequently opposites. `Complete_Quran_data`'s `Fear` label co-occurs with judgment content in
1,614 of 1,823 assignments (89%) — mapping it to "user feels fear" would serve punishment verses
to frightened people. `build_ledger.make_targets` raises on any attempt; test 5 asserts it.

**2. Cross-reference votes enter nothing.**
Votes measure how many people liked a *link*. Only edge structure and location are used, and only
to corroborate. Every cross-reference feature is `null` for all 6,236 Quran records, and the
cascade may not read it — otherwise 31,103 Bible verses would gain a feature the Quran cannot
have and the asymmetry would invert. Tests 6 and 16.

**3. The model proposes; the cascade decides.**
Gemini supplies evidence. `curation.py` computes the status by an ordered rule cascade, first
match wins, and records `rule_fired`. Changing a threshold re-runs over existing annotations
without re-annotating anything. Default deny: a record matching no INCLUDE rule falls to
`REVIEW_REQUIRED`.

## What is deliberately not done

- No embeddings, no pgvector, no database models, no API, no Flutter — those are Phase 2 and 3.
- No source label is corrected in the corpus. Typos, near-duplicates and column bleed are recorded
  in the ledger and quarantine, exactly as Phase 0 reported them without repair.
- No gold set exists yet, so no field's reliability is measured. `validation/agreement_report.json`
  says so rather than implying a quality it cannot demonstrate.
- The 105 ayat whose Arabic diverges across sources have no display decision. They route to review.
