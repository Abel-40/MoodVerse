# MoodVerse — Phase 1 enrichment layer

Converts the Phase 0 source-faithful corpus into a curated reflection corpus, **without ever
modifying Phase 0**. Every artefact here is additive; the join to the corpus happens at read time.

## Status

The deterministic half is complete and passing. The annotation half is built and waiting for a
Gemini API key — until a run exists, every record is `REVIEW_REQUIRED` via `gate1.not_annotated`,
which is the correct default-deny behaviour rather than a bug.

## Running it

```bash
cd processed/enrichment

python build_label_inventory.py     # scan the corpus for every source label
python build_ledger.py              # map those labels into the taxonomy
python build_priors.py              # deterministic signals for all 37,339 records
python build_docs.py                # regenerate definitions.md and mapping_rules.md

# annotation (needs GEMINI_API_KEY; --dry-run works without one)
python annotate.py --tier high_yield --limit 200

python build_enrichment.py --bootstrap   # assemble; --bootstrap accepts unreviewed ledger rows
python validate.py                       # 14 structural checks + parity/coverage reports
python tests/test_phase1.py              # 18 tests
```

`build_enrichment.py` is a **pure function** of (corpus + taxonomy + ledger + priors + recorded
runs + overrides). Re-running it makes zero API calls and produces byte-identical output — test 2
asserts this.

> **Note on the corpus size.** The Bible carries **31,103** verses, not the published AKJV's 31,103.
> 3 John 1:14 was split at its sentence boundary in this workspace's copy so the cross-reference
> file's versification resolves; no words were added, and the two verses concatenate to the
> original. See limitation 8 in `processed/clarification.md`.

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
| `annotation/prompts/annotate_verse.md` | The Gemini contract |
| `annotate.py` | The only file that makes network calls |
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
