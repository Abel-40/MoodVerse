# MoodVerse — Phase 1B report

**Pipeline version** `1.0.0` · **Taxonomy** `1.0.0` · **Enrichment schema** `phase1-1`
**Ledger schema** `1.0.0` · **Priors** `1.0.0`

Written in the register of Phase 0's `clarification.md`: what was done, what was deliberately not
done, and what remains unresolved.

---

## 1. Exit criteria

Against the criteria in `implementation_phases.md`:

| Criterion | Status | Evidence |
| --- | --- | --- |
| taxonomy defined | **done** | `taxonomy/taxonomy.json` — 17 emotions, 47 themes, 17 intents, 30 situations, 18 scripture purposes, 5 context levels, 14 dependency reasons, 11 blockers, 10 advisories |
| mappings are reversible | **done** | 671 ledger rows, one per (source, type, label). Tests 3 and 4 assert the round trip in both directions |
| enrichment schema validated | **done** | 14 structural checks, all passing over 37,339 records |
| curation rules implemented | **done** | `curation.py`, 21 rules across 4 gates. Tests 8–10 |
| enrichment generated | **partial** | 37,339 records generated; all `REVIEW_REQUIRED` pending annotation. See §4 |
| provenance preserved | **done** | Per-field-group provenance, 6-rank ladder, evidence block naming every contributing label |
| validation passes | **done** | 14/14 checks, 18/18 tests |
| Phase 0 files remain unchanged | **done** | 34 files hashed before and after every run; test 1 |

**Phase 1 is not complete.** The deterministic half is finished and verified. The annotation half
is built and blocked on a Gemini API key.

---

## 2. What was built

| Artefact | Size | Notes |
| --- | ---: | --- |
| `taxonomy/taxonomy.json` | 53 KB | Hand-authored; the single source of truth |
| `taxonomy/definitions.md` | 30 KB | Generated from it, so prose cannot drift from the enforced vocabulary |
| `mappings/label_inventory.json` | 405 KB | 671 distinct labels across 11 vocabularies |
| `mappings/source_label_ledger.json` | 827 KB | 671 rows; 501 from independent sources |
| `mappings/quarantine.json` | 86 KB | 159 low-frequency labels, preserved not deleted |
| `priors/deterministic_priors.jsonl` | 32 MB | 18 rules over all 37,339 records |
| `curation/enrichment.jsonl` | 87 MB | 37,339 enrichment records |
| `curation/decisions.jsonl` | 9.7 MB | Status + `rule_fired`, separable from the record |
| `schemas/gemini_response.schema.json` | 32 KB | Generated from the taxonomy |
| `annotation/prompts/annotate_verse.md` | 7.3 KB | The Gemini contract |

Code: `mv_common.py`, `build_label_inventory.py`, `ledger_rules.py`, `build_ledger.py`,
`build_priors.py`, `curation.py`, `build_enrichment.py`, `validate.py`, `build_docs.py`,
`annotate.py`, `tests/test_phase1.py`. Standard library only, matching Phase 0.

---

## 3. Findings that changed the implementation

Six things came up while building that the design did not predict.

### 3.1 The design's connective figure was attached to the wrong word list

`PHASE1A_DESIGN.md` cited 19,606 verses (63.0%) opening with a discourse connective, listing 13
words. That count came from a 24-word case-insensitive regex that also included `That`, `Which`,
`Who`, `When`, `If`, `Or`, `Nor` — relative pronouns and subordinators, which are much weaker
evidence of discourse dependency (*"If a man shall steal…"* opens a self-contained law).

For the 13 words actually documented, the measured figure is **18,107 (58.2%)**. The design
document has been corrected, and the prior ships with the narrow list.

### 3.2 Two prior thresholds were calibrated after measurement, not before

- **Range membership.** The design proposed firing when a verse falls inside ≥5 OpenBible range
  targets. Measured distribution: median 8, p75 15, p90 24. A threshold of 5 fires on **73.7%** of
  Bible verses — a constant, not a signal. Raised to 20, which fires on 16.0%.
- **Referrer spread.** Likewise ≥8 books is merely the median and fired on 55.4%. Raised to 20,
  which fires on 8.7%.

Both were caught only because firing rates were printed and inspected.

### 3.3 The QSAC type prior was wrong on the verse it most needed to get right

The design said tags of ontology type `ruling`, `event` or `entity` predict low standalone
usefulness. Implemented as "fires if any such tag is present", it gave **`quran:94:5`** — *"For
indeed, with hardship [will be] ease"*, the clearest example of an excellent standalone reflection
in the corpus — a **−1 standalone_usefulness** nudge, because one of its four tags is typed
`event` while two are `concept`.

The rule now compares which group *dominates* rather than which is *present*. `quran:94:5` now
correctly receives +1.

### 3.4 The design's fan-out example was unsafe

`PHASE1A_DESIGN.md` §3.6 sketched mapping `Guidance` to both theme `divine_guidance` and intent
`guidance`. On implementation that is wrong: an intent is a claim that a verse *performs a
pastoral act well*, which is a suitability judgement. No source — least of all one with no stated
methodology — is entitled to make it.

`intent` and every `*_suitability` field were therefore added to the ledger's forbidden-axis list
alongside `addressed_states`. Source labels describe content; they do not certify usefulness.

### 3.5 The AKJV copy was amended after the first build

Partway through Phase 1B the workspace's `AKJV.xml` was edited to add 3 John 1:15, which the
published American King James Version does not have — its 3 John ends at verse 14.

The first attempt appended a new verse whose text duplicated the second half of verse 14, and
closed with a mismatched `</vnumber>` tag that made the file unparseable. Both were caught before
any rebuild ran, because the pipeline validates its inputs before it writes anything.

The resolution splits verse 14 at its sentence boundary instead:

```
v14: But I trust I shall shortly see you, and we shall speak face to face.
v15: Peace be to you. Our friends salute you. Greet the friends by name.
```

**No words were added or altered** — the two verses concatenate to the original verse 14 exactly,
verified programmatically. This is a versification change, which is precisely what was mismatched
with the cross-reference file, rather than a translation change.

Consequences, all verified after the rebuild:

| | Before | After |
| --- | ---: | ---: |
| Bible verses | 31,102 | 31,103 |
| Total records | 37,338 | 37,339 |
| Cross-reference edges attached | 344,755 | 344,756 |
| Edges unresolved | 5 | **0** |
| Edges attachable to no record | 1 | **0** |
| Records with unresolved mappings | 4 | **0** |

`bible:1 John:3:18`, `bible:2 John:1:1`, `bible:1 Peter:5:1` and `bible:Acts of the
Apostles:11:30` were previously held at `REVIEW_REQUIRED` by `gate1.phase0_data_quality` because
one of their cross-references pointed past the end of 3 John. All four are now `valid` and will be
judged on their own merits.

The provenance documents were made to say this rather than assume it: `source_catalog.json` and
`clarification.md` now state that this copy is amended and no longer matches the published AKJV,
and revert to the original wording automatically if the split is ever undone.

### 3.6 The column-bleed detector over-flagged by 8×

An initial detector flagged 48 labels as column bleed. 42 were benign vocabulary reuse — the same
word used as both a theme and an emotion, e.g. `Fear`, which is normal. Restricting bleed
detection to the `category`↔`context` pair that Phase 0 actually documented yields exactly **6**
(the 3 labels Phase 0 named, doubled by the derived TCEC copy).

Separately, the original detector *missed* every typo variant, because it normalised punctuation
and case but the typos differ by letters. A similarity pass at 0.88 catches all of them
(`Spiritality`/`Spiritivity`/`Spirituality`, `Akhlaak`/`Akhlaq`, `Eschological`/`Eschatological`,
`Miracle`/`Miracles`) with zero false positives; the nearest non-variant pair, `Injustice`/
`Justice`, sits at 0.875.

Worth recording: **`Eschological context` (947) is more frequent than the correct
`Eschatological context` (398)**, so frequency cannot be used to identify the canonical spelling.

---

## 4. Current state of the corpus

All 37,339 records are `REVIEW_REQUIRED`, every one via `gate1.not_annotated`.

This is the **correct default-deny result for an unannotated corpus**, not a failure. It also
proves the property that matters most: nothing can reach a user by falling through the cascade.

```
bible: {'REVIEW_REQUIRED': 31103}
quran: {'REVIEW_REQUIRED': 6236}
```

Parity reports 26 gaps (13 product purposes × 2 religions) and `gate_passed: false`, which is the
honest reading of a corpus with zero annotation coverage.

---

## 5. Limitations

1. **No annotation exists.** Every judgement field is null. The pipeline is verified end to end
   against fixtures, not against real model output.
2. **No gold set, so no field's reliability is known.** `validation/agreement_report.json` states
   this rather than implying a quality it cannot show. Until it exists, the cascade's
   `gate1.field_below_agreement_threshold` has nothing to act on.
3. **All 671 ledger rows are `proposed`, none `approved`.** The build currently runs with
   `--bootstrap`, which accepts proposed rows and stamps `bootstrap: true` on every affected
   record so no unreviewed mapping can be mistaken for a reviewed one. 501 rows need human review.
4. **`bible.opens_with_connective` is partly a translation artefact.** KJV renders the Hebrew
   waw-consecutive as "And", so 58.2% overstates genuine syntactic dependency.
5. **The connective rule sees syntax only.** Song of Solomon has the canon's lowest connective
   rate (0.09) and among its highest genuine context dependency.
6. **`bible.genealogy_pattern` is lexical and misses pure name lists.** `bible:1 Chronicles:1:1`
   ("Adam, Sheth, Enosh") triggers no pattern and is not flagged.
7. **QSAC types are LLM-assigned**, like the tags. The ontology is published and validated; the
   per-tag type assignment was not human-adjudicated.
8. **The Quran has no genre prior** because no Phase 0 source supplies one. None was invented.
9. **The 105 divergent Arabic readings still have no display decision.** Those records route to
   `gate1.undecided_display_text`.
10. **`display_text_ref` currently records a deterministic default** — Saheeh International, else
    Complete_Quran_data English — which is a *rendering* choice, not a ruling on which Arabic
    reading is correct.

---

## 6. Unresolved, needing a decision

| # | Question | Why it is blocking |
| ---: | --- | --- |
| 1 | Gemini API key | Blocks all annotation. `annotate.py` reads `GEMINI_API_KEY` from the environment or a gitignored `.env` |
| 2 | Who reviews the 501 ledger rows | Until then the build runs in bootstrap mode |
| 3 | Who annotates the ~600-verse gold set | Without it, no field's reliability can be measured, and no record can honestly reach `approved_production` |
| 4 | Which Arabic reading displays for the 105 divergent ayat, and the default Quran translation | A content decision. 2,172 records carry a variant flag |
| 5 | Full coverage in one pass, or tiered? | Currently tiered: `--tier high_yield` selects poetry/wisdom and epistles with non-dependent openings, plus the full Quran |
| 6 | Parity gate N = 20 INCLUDE verses per (purpose × religion) | Currently proposed; a product call |

---

## 7. What Phase 1B did NOT do

By design, and unchanged from Phase 0's list:

- No embeddings, vector index, pgvector, PostgreSQL schema, migration or ingestion.
- No semantic retrieval, recommendation or ranking.
- No FastAPI or any API surface. No Flutter or client code.
- No modification of any Phase 0 artefact or raw source. 34 files are hashed before and after
  every run; the build aborts on any change.
- No repair of any source label. Typos, near-duplicates and column bleed are recorded in the
  ledger and quarantine and left exactly as published.
- No composite or overall score. Ranking weights belong to Phase 2, where they are visible.
- No curation status decided by a model.
