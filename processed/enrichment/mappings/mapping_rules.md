# Source-label mapping rules

Ledger schema `1.0.0`, taxonomy `1.0.0`. **Generated from `source_label_ledger.json` by `build_docs.py` - do not edit by hand.** The declared rules live in `processed/enrichment/ledger_rules.py`.

## Policy

- **reversibility** - Every row preserves the source label verbatim alongside its mapping, so the corpus can be re-derived forward and any enrichment value can be traced back to the labels that contributed to it.
- **corpus untouched** - Applying this ledger is a join at read time. No value in unified_scripture_corpus.jsonl is altered, and spelling variants keep the source's own spelling.
- **forbidden axes** - `addressed_states, addresses_states, curation_status, emotional_relevance, intent, intents, purpose_suitability, standalone_usefulness`
- **forbidden axes reason** - Source annotations describe what the text expresses. None of them measures which user state a verse serves, and none is entitled to certify pastoral suitability. Both prohibitions are asserted at build time.
- **approval** - Rows are emitted as `proposed`. A row carries evidence weight only once a human reviewer sets status to `approved`.

## Totals

| Metric | Value |
| --- | ---: |
| Ledger rows | 671 |
| From independent sources | 501 |
| From derived sources (weight 0) | 170 |
| Quarantined | 159 |

Targets by axis: `expressed_affect` 24, `none` 12, `scripture_purpose_prior` 213, `structural` 4, `theme` 639.

## Vocabularies

| Source | Annotation type | Rows | Tier | Independent |
| --- | --- | ---: | --- | :---: |
| Complete_Quran_data | category | 19 | `undocumented` | yes |
| Complete_Quran_data | context | 11 | `undocumented` | yes |
| Complete_Quran_data | emotion | 22 | `undocumented` | yes |
| Complete_Quran_data | theme_tag | 118 | `undocumented` | yes |
| ELQV | emotion | 4 | `expert_human` | yes |
| ELQVv2 | emotion | 4 | `derived` | yes |
| Only TCEC cols | category | 19 | `derived` | no |
| Only TCEC cols | context | 11 | `derived` | no |
| Only TCEC cols | emotion | 22 | `derived` | no |
| Only TCEC cols | theme_tag | 118 | `derived` | no |
| QSAC | semantic_tag | 323 | `ontology_guided_llm` | yes |

## Quarantine

Labels here are preserved and visible but contribute nothing to any aggregate. Nothing is deleted or corrected in the corpus. Quarantine is a decision recorded for review, not a repair.

159 labels are quarantined, all for `low_frequency` (<= 2 occurrences).

## Worked examples

The three rows that show most clearly what the ledger is for.

### `Fear` - Complete_Quran_data / emotion (1,823 occurrences)

- targets: `expressed_affect:fear` (broader, 0.4)
- tier: `undocumented` (weight 0.3)
- rationale: Measured: 1614 of 1823 assignments (89%) fall on judgment or punishment content, so this label largely marks verses ABOUT dread rather than verses FOR the frightened. Mapped to expressed_affect only, at low confidence. It has no path to addressed_states.

### `Fear` - Complete_Quran_data / theme_tag (901 occurrences)

- targets: `theme:afterlife_punishment` (related, 0.3)
- tier: `undocumented` (weight 0.3)
- rationale: In the theme column this marks passages ABOUT the fear of punishment, not passages that console the fearful. Mapped to `afterlife_punishment` for that reason. Mapping it to an emotion here would be the direction error the taxonomy exists to prevent.

### `Makki Revelation` - Complete_Quran_data / context (975 occurrences)

- targets: `structural:revelation_period=makki` (exact, 0.7)
- tier: `undocumented` (weight 0.3)
- rationale: Revelation chronology is a structural fact about the text, not a semantic or emotional one. Given its own field rather than forced onto a taxonomy axis.
