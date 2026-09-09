# MoodVerse — Phase 1A: Curation & Enrichment System Design

**Status:** DESIGN ONLY — nothing in this document has been implemented.
**Depends on:** Phase 0 (`processed/`, pipeline `0.2.0`, corpus schema `phase0-2`) — treated as frozen and authoritative.
**Proposed artefact versions:** taxonomy `1.0.0`, enrichment schema `phase1-1`, ledger schema `1.0.0`.

> **Addendum — 2026-09-09.** The corpus figures in section 1 describe the corpus as it stood when
> this analysis was written: 31,102 Bible verses, 37,338 records, 5 unresolved cross-references.
> The workspace's `AKJV.xml` has since been amended — 3 John 1:14 is split at its sentence
> boundary, adding no words, so the cross-reference file's versification resolves. The corpus is
> now **31,103 / 37,339 records with 0 unresolved references**, and the four records that were
> held at `REVIEW_REQUIRED` over `3John.1.15` are now `valid`. Every proportion, distribution and
> conclusion in this document is unaffected by a one-verse change. See §3.5 of
> `processed/enrichment/PHASE1B_REPORT.md` and limitation 8 of `processed/clarification.md`.

---

## 1. Analysis of the Phase 0 corpus

Everything below was measured against `processed/unified_scripture_corpus.jsonl`,
`processed/qsac_ontology.json`, `processed/source_catalog.json`,
`processed/validation_report.json`, `processed/source_mapping_report.json` and
`processed/unresolved_records.json`. No property is assumed that the artefacts do not state or
that I did not compute directly from them.

### 1.1 Shape of the corpus

| | Bible | Quran |
|---|---:|---:|
| Records | 31,102 | 6,236 |
| Share of corpus | 83.3% | 16.7% |
| Translations available | 1 (AKJV) | up to 10 per verse |
| Semantic/thematic annotations | **0** | 49,546 (independent sources only) |
| Emotion annotations | **0** | 8,727 (independent sources only) |
| Cross-reference edges | 344,755 | 0 |
| `data_quality` valid / warning / unresolved | 30,982 / 116 / 4 | 6,232 / 4 / 0 |

The corpus is not merely asymmetric: **83% of it carries no semantic metadata at all.** The Bible
side is scripture text plus a citation graph. This single fact determines most of the design.

### 1.2 Bible coverage and available metadata

- 66 books, 1,189 chapters, 31,102 verses, 0 empty, 0 duplicate ids, KJV versification.
- Per record: `location.book / book_number / book_short_name / osis_book_id / chapter / verse_start /
  verse_end`, one `text.original` (AKJV, English), `cross_references[]`, `source_provenance[]`,
  `data_quality`.
- `source_annotations[]` contains exactly one entry per Bible record: `AKJV / verse_text`, which
  duplicates `text.original`. Phase 0 states it is retained for v0.1 compatibility and must be
  ignored by annotation aggregation. **There is no thematic, emotional, semantic or genre annotation
  on any Bible verse.**
- Verse length: mean 25.4 words, p5 11, median 24, p75 32, p95 46, max 90. 212 verses (0.7%) are
  6 words or fewer.
- Distribution by book is heavily skewed: Psalms 2,461; Genesis 1,533; Jeremiah 1,364; Isaiah 1,292;
  down to 2 John 13 and 3 John 14.

**Derived (not source-provided) structure I computed, usable as deterministic priors:**

| Genre grouping | Verses |
|---|---:|
| narrative (historical books + Acts) | 9,962 |
| prophetic | 5,336 |
| poetry / wisdom (Ps, Prov, Eccl, Song, Job, Lam) | 4,939 |
| law (Exod, Lev, Num, Deut) | 4,319 |
| gospel | 3,779 |
| epistle | 2,767 |

| Textual signal | Verses | Share |
|---|---:|---:|
| Opens with a discourse connective (`And`, `But`, `For`, `Therefore`, `So`, `Then`, `Thus`, `Wherefore`, `Nevertheless`, `Moreover`, `Yet`, `Now`, `Because`) | 18,107 | **58.2%** |
| Opens with an unbound pronoun (`He`, `They`, `It`, `This`, `Those`, …) | 1,833 | 5.9% |
| Contains a speech verb (`said`, `saith`, `answered`, `spake`) | 4,857 | 15.6% |
| Matches genealogy / measurement patterns (`begat`, `the son of`, `cubits`, `numbered`, `years old`) | 1,535 | 4.9% |
| Is a chapter opening (verse 1) | 1,189 | 3.8% |

The connective rate varies enormously by book — Judges 0.91, 1 Samuel 0.90, Ruth 0.89, Mark 0.88,
Genesis 0.86 versus Psalms 0.22, Proverbs 0.16, Lamentations 0.10, Song of Solomon 0.09. This is a
strong, free, fully explainable prior for context dependency. **Its limitation must be stated
honestly:** KJV's `And` frequently renders a Hebrew *waw*-consecutive and is a translation artefact,
so the signal is a prior with a real false-positive rate, never a verdict, and must be overridable.
It also measures only *syntactic* dependency — Song of Solomon has the lowest connective rate in the
canon and among the highest genuine context-dependency.

### 1.3 Quran coverage and available metadata

- 114 surahs, 6,236 ayat, contiguous, 0 invalid identifiers.
- No source supplies surah names for all 114 surahs, so `location.book_or_surah` is the constructed
  label `"Surah N"`. **The enrichment layer must not invent surah names either.**
- Every ayah carries Arabic (`text.original`, from `Complete_Quran_data`), plus Urdu and English
  (`Complete_Quran_data`) and Saheeh International (`QSAC`). 2,087 ayat additionally carry seven
  ELQVv2 English translations.
- 105 ayat have divergent Arabic across sources (`Complete_Quran_data` prepends the Basmala to ayah 1
  of surahs 10–114; QSAC does not). 2,172 records carry at least one `text.original_variants[]` entry.
  Phase 0 deliberately did not choose a reading.

### 1.4 Source annotations

Independent annotation sources, per Phase 0's own provenance flags:

| Source | Type | Coverage | Per-verse density | Methodology stated in source |
|---|---|---:|---:|---|
| `Complete_Quran_data` | theme_tag / category / emotion / context | 6,236 (100%) | 5.33 themes, 1.40 emotions | **none** |
| `QSAC` | semantic_tag | 6,236 (100%) | 2.61 tags | LLM-assisted, ontology-guided |
| `ELQV` | emotion | 2,087 (33.5%) | ~1.0 | 24 PhD specialists, documented selection criteria |

Derived, and **must be excluded from any aggregation**: `Only TCEC cols` (52,565 annotations,
verified cell-identical to `Complete_Quran_data`) and `ELQVv2` (2,092 emotion annotations, verified
label-identical to `ELQV`). Together they are 54,657 of the 156,722 stored annotations — **35% of
the annotation volume is duplicate**. Naive pooling double-counts one annotator as two.

### 1.5 ELQV / ELQVv2

- 2,100 rows, 2,087 distinct verses, four classes only: `fear` 672, `joy` 586, `anger` 494,
  `sadness` 340 (stored assignments).
- The strongest evidential provenance in the corpus: 24 annotators holding PhDs in Quranic sciences,
  Hadith or Arabic linguistics, with published inclusion/exclusion criteria.
- ELQVv2 agrees with ELQV on every shared verse (0 disagreements at build time). One opinion, two files.
- 4 verses carry more than one label (`quran:20:12` fear+joy; `quran:26:8` anger+fear+sadness;
  `quran:26:172` and `quran:79:17` anger+fear). Phase 0 kept every label.

**Two limitations that matter more than the quality of the annotation:**

1. **The label set has no positive-supportive class.** anger + fear + sadness = 1,506 of 2,092
   assignments (72%). There is no `comfort`, `hope`, `peace` or `assurance` class. ELQV is an
   emotion-*detection* research resource, not a pastoral-fit resource.
2. **It covers a third of the Quran and none of the Bible.** Using it as a quality signal would
   privilege 2,087 verses out of 37,338.

### 1.6 QSAC ontology

- Version `1.0`, 18 domains, 70 categories, 338 tags, 0 duplicate names. Copied byte-identically;
  the SHA-256 of the copy equals the source's, so it is provably unmodified.
- 323 tags are used by the dataset; 15 are unused. 0 dataset tags fall outside the ontology.
- Each tag carries a `description`, `keywords.primary`, `keywords.secondary`, and a `types[]` list.
- The `types` vocabulary is the most immediately useful part of the ontology for this phase:

  `concept` 196 · `event` 68 · `ruling` 61 · `moral_trait` 55 · `practice` 52 · `entity` 45 ·
  `directive` 37 · `sign` 22

  `ruling`, `event` and `entity` tags are direct predictors of low standalone usefulness and high
  context dependency; `concept` and `moral_trait` are the opposite. This is a *structural* signal in
  a documented ontology — safe to use as a prior without importing QSAC's vocabulary.
- Limitations: tags are thematic, never emotional; they are LLM-generated with ontology guidance and
  not human-adjudicated; and the ontology is Islamic in vocabulary and structure, so it cannot be
  extended to the Bible without becoming an interpretive act. **QSAC is evidence, not a taxonomy to
  adopt.**

### 1.7 `Complete_Quran_data` annotations

The most heavily used source, and the weakest evidence in the corpus.

- **Provenance is unknown.** The file states no methodology, annotator, or licence.
- **The `emotion` vocabulary is degenerate for retrieval.** 22 distinct values, but
  `Fear` (1,823) + `Awe` (1,820) = 55% of all 6,635 assignments. Meanwhile the labels MoodVerse most
  needs are vanishingly rare: `Comfort` 135, `Patience` 80, `Joy` 39, `Humility` 26, `Compassion` 18,
  `Guidance` 10. Six values occur twice or less (`Challenge` 1, `Justice` 1, `Warning` 1,
  `Arrogance` 2, `Faith` 2, `Kindness` 2) and several of the 22 are not emotions at all
  (`Guidance`, `Faith`, `Justice`, `Warning`).
- **Vocabulary hygiene is poor**, exactly as Phase 0 reported: `Supplication & Spiritality` /
  `Spiritivity` / `Spirituality`; `Worship (‘Ibadah)` / `(‘Ibadah)'` / `(‘Ibadah)’`;
  `Ethics & Morality (Akhlaak)` / `(Akhlaq)`; `Eschological context` / `Eschatological context`;
  `Divine Decree` / `Divine decree`.
- **Column bleed is demonstrable.** `Moral teaching context`, `Spiritual reminder` and `Revelation`
  appear in *both* the `category` and the `context` vocabularies. Some `category` cells hold context
  values.
- The `context` column mixes two incompatible things: discourse type (`Historical story`,
  `Law-giving context`, `Spiritual reminder`) and revelation chronology (`Makki Revelation` 975,
  `Madani Revelation` 159). These are not the same kind of fact and must not land on the same axis.

### 1.8 The single most important finding: annotation *direction*

**Every emotion label in every source describes the affect the text expresses or evokes. None
describes the user state the verse is a good answer to.** These are opposite directions, and the
corpus proves the gap is large, not subtle.

Co-occurrence of `Complete_Quran_data` emotion labels with judgment/punishment content
(theme or QSAC tag in {Punishment, Hell, Disbelief, Hypocrisy, Misguidance, Divine Punishment,
Punishments of Hell, Description of Hellfire, Destroyed Nations, Rejection of Prophets, Shirk}):

| Emotion label | on judgment content | elsewhere | % judgment |
|---|---:|---:|---:|
| `Anger at Injustice` | 412 | 27 | **94%** |
| `Sadness` | 240 | 18 | **93%** |
| `Fear` | 1,614 | 209 | **89%** |
| `Determination` | 297 | 253 | 54% |
| `Repentance` | 48 | 64 | 43% |
| `Awe` | 703 | 1,117 | 39% |
| `Patience` | 30 | 50 | 38% |
| `Comfort` | 33 | 102 | 24% |
| `Hope` | 128 | 735 | 15% |
| `Gratitude` | 38 | 332 | 10% |
| `Love of Allah` | 3 | 62 | 5% |

Worked example — `quran:2:7`, labelled `emotion: Fear`:

> "Allah has set a seal upon their hearts and upon their hearing, and over their vision is a veil.
> And for them is a great punishment."

A pipeline that maps *"user feels fear"* onto *"verses labelled Fear"* would put this in front of a
frightened user. There are **1,614 such verses**. This is precisely the harm the product requirement
describes, and it is already latent in the source data — it does not need to be introduced by a
mistake in Phase 1B, it arrives by default if the labels are taken at face value.

**Design consequence:** MoodVerse must model two separate emotional axes —
`expressed_affect` (what the text *sounds like*) and `addressed_states` (what user state it *serves*)
— and source emotion labels may map **only** to the first. This is enforced mechanically in §3.

A second consequence: 55.3% of Quran ayat (3,446) carry judgment/punishment content. The
default-recommendation pool will be a minority of the corpus on both sides, and the exclusion
machinery has to be load-bearing, not a safety net.

### 1.9 Cross-reference information

- 344,756 edges in `cross_reference_graph.json` (authoritative); 344,755 attached to records;
  1 unattachable because its *source* verse is absent from AKJV.
- 29,362 Bible records carry edges; **1,740 carry none**. Mean 11.7 edges per referencing record
  (median 7, p95 27, max 97).
- Vote distribution: median 3, p75 6, p90 12, p95 20, p99 58, max 1,291. 1,243 negative, 2,271 zero.
  Votes are an OpenBible community up/down weight — not relevance, not similarity, not normalised.
- 88,130 targets (25.6%) are ranges; 18 cross a book boundary. Ranges are not expanded.
- The graph is Protestant-canon, English-language, community-sourced in origin.
- **The Quran has zero cross-references.** Any feature derived from this graph exists for 31,102
  records and cannot exist for 6,236. Using it in a score would not just misrepresent relevance — it
  would invert the asymmetry problem.

### 1.10 Provenance differences

Four distinct kinds of evidence sit in the corpus and must never be pooled:

| Tier | Sources | Character |
|---|---|---|
| Expert human | ELQV (+ ELQVv2, derived) | Documented panel, published criteria; 4 classes, 33.5% of Quran |
| Ontology-guided LLM | QSAC | Documented method, validated against a published ontology, 0 out-of-ontology tags |
| Undocumented | Complete_Quran_data (+ Only TCEC cols, derived) | No methodology, no annotator, no licence; dirty vocabulary |
| Community vote | OpenBible cross references | Aggregate popularity of a *link*, not a judgement about a verse |
| None | AKJV | Scripture text only |

### 1.11 Known data-quality warnings carried forward

- 120 records `warning`, 4 records `unresolved`, 0 `error`.
- `original_text_variant_across_sources` — 105 records. A display decision is owed here.
- `repeated_source_rows` — 12 records; `repeated_tag_within_source_row` — 3 records;
  `multiple_labels_from_single_source` — 4 records.
- `unresolved_cross_reference_target` — 4 records, all pointing at `3John.1.15`, which does not exist
  in KJV versification. A genuine source disagreement, unrepaired.

### 1.12 Limitations that must influence curation

1. **The Bible has no source annotations.** Enrichment cannot be a mapping exercise; it must be a
   generation exercise, applied uniformly to both corpora.
2. **Source emotion labels point the wrong way** (§1.8). They are evidence about the text, never
   about the reader.
3. **`Complete_Quran_data` is the highest-volume and lowest-provenance source.** Volume must not be
   mistaken for weight.
4. **35% of stored annotations are duplicates** and are only distinguishable by the
   `independent_annotation` / `independent_annotation_source` flags.
5. **QSAC's ontology is Islamic in structure** and cannot be extended across religions without
   interpretation.
6. **Cross-reference votes are Bible-only and are not a relevance measure.**
7. **No surah names exist**; none may be invented.
8. **105 Arabic readings diverge**; a display decision must be recorded, not defaulted.
9. **Source vocabularies contain typos, near-duplicates and column bleed**, deliberately unrepaired.
   Any normalisation must live in a mapping ledger, never in the corpus.
10. **Operational:** the corpus is UTF-8, but the default Windows console codepage here is cp1252 —
    printing Arabic without an explicit encoding raises `UnicodeEncodeError`. Phase 1B must open every
    file with `encoding="utf-8"` and set stream encoding explicitly.

---

## 2. The MoodVerse controlled taxonomy

**Design principles.** Every vocabulary below is closed, versioned, religion-neutral in wording,
independent of any source dataset's terminology, and defined by what it *excludes* as much as by what
it includes. Values are `snake_case` stable identifiers (safe as DB enums and as JSON-schema enum
members); display labels live in the taxonomy file and may change without a data migration. Each
axis is separately documented within one `taxonomy.json` carrying a single semver
`taxonomy_version`; adding a value is a minor bump, removing or re-meaning one is a major bump that
requires re-annotation of affected records.

**The organising decision:** the emotion vocabulary is used on **two distinct axes**.

- `expressed_affect` — the emotional register *of the text*. This is where all source emotion labels
  land.
- `addressed_states` — the user emotional states the verse is a **fit response to**. This is what
  retrieval joins against. Nothing in any source measures this.

One vocabulary, two axes, never interchangeable.

### A. Primary emotions (17)

Used for both axes. `primary` is a single value; `secondary` is an ordered list.

**Definition.** A felt emotional state, as a person would name it about themselves, at the
granularity a scripture response can meaningfully differ on.
**Inclusion criteria.** (i) A user could plausibly type it about themselves; (ii) the appropriate
pastoral response differs from every other value in the list; (iii) it is a state, not a situation,
a virtue, or a request.
**Exclusion criteria.** Situations (`bereavement` — axis F), spiritual acts (`repentance` — axis E),
virtues and dispositions (`humility`, `faith`), theological postures (`fear of God` — that is
`awe`), and clinical diagnoses (never used; `mental_health_struggle` is a situation, not an emotion).

| Value | Definition | Boundary against the nearest neighbour |
|---|---|---|
| `anxiety` | Anticipatory dread about an uncertain future | vs `fear`: no identified present object |
| `fear` | Fear of a present, identified threat | vs `anxiety`: object-specific and immediate |
| `grief` | Sorrow arising from a specific, irrecoverable loss | vs `sadness`: has an identifiable loss |
| `sadness` | Low mood, heaviness, discouragement without a specific loss | vs `grief`: no locus |
| `loneliness` | Felt absence of connection — human or divine | vs `sadness`: relational in content |
| `anger` | Indignation, including at injustice, at another, or at God | Low-intensity frustration is `anger` at intensity 1 |
| `guilt` | Distress about something one **did** | vs `shame`: act-focused, repairable |
| `shame` | Distress about what one **is** | vs `guilt`: identity-focused, not repaired by apology |
| `despair` | Hopelessness; the belief that nothing will change | vs `sadness`: forward-looking and totalising. **Safety-critical — see §6** |
| `exhaustion` | Depletion, burnout, weariness | vs `sadness`: capacity, not mood |
| `confusion` | Not knowing what to do; decision paralysis | vs `doubt`: practical, not spiritual |
| `doubt` | Uncertainty about God, faith, or being heard | vs `confusion`: spiritual object |
| `gratitude` | Thankfulness seeking expression | vs `joy`: directed at a giver |
| `joy` | Happiness, gladness, celebration | vs `gratitude`: undirected |
| `awe` | Wonder and reverence before greatness; smallness | vs `fear`: not aversive |
| `peace` | Settledness, calm, contentment | See ambiguity note below |
| `hope` | Forward-looking expectation of good | vs `joy`: not yet realised |

**Documented ambiguities** (decided by rule, not left to the annotator's taste):

- *"I need peace"* — the user's **state** is `anxiety` (or whatever the turmoil is); `peace` is the
  **intent** (axis E). Rule: when an input names a desired state, the desired state goes to intent
  and the present state goes to emotion. `peace` appears as an emotional state only when the user
  reports currently having it.
- `anxiety` / `fear` overlap in everyday speech. Rule: absent an identified object, use `anxiety`.
- `guilt` / `shame` are frequently co-reported. Rule: primary = whichever the text or user names
  more specifically; the other goes to secondary.
- `awe` is the correct target for source labels rendered "fear of Allah" / "fear of the LORD" —
  **never** `fear`. This mapping rule alone prevents a large class of the §1.8 error.

### B. Secondary emotions

**The same 17-value vocabulary**, as an ordered list, maximum 3, never repeating the primary.

*Why not a second, finer vocabulary:* one vocabulary means one enum, one embedding space, no
inter-vocabulary mapping, and no drift between "primary sadness" and "secondary sorrow". A second
vocabulary would double the maintenance and halve the auditability.

**Extensibility hatch.** An open, non-retrieval field `nuance_terms[]` (≤3, lowercase, free text)
records shades the closed list cannot carry. It is never queried and never filtered on. Terms that
recur above a threshold across a release become candidates for promotion into the closed vocabulary
at the next minor version bump. This gives the taxonomy a measured growth path instead of ad-hoc
additions.

### C. Emotional intensity

Ordinal 1–4, with behavioural anchors. **Not** 1–10: a 10-point scale invites annotators (human or
model) to express confidence as precision, and the resulting differences between 6 and 7 are noise.

| Level | Name | Anchor |
|---:|---|---|
| 1 | `low` | Present in the background; the person is functioning normally |
| 2 | `moderate` | Clearly felt and named; functioning with effort |
| 3 | `high` | Acute and dominating; hard to function |
| 4 | `crisis` | Overwhelming; safety-relevant |

**Two fields, not one:**

- `text_intensity` (1–4) — the emotional force of the verse itself.
- `serves_intensity` `{min, max}` — the *interval* of user intensity this verse serves well.

The interval matters. "Be still, and know that I am God" is right at 1–2 and can read as dismissive
at 4. "Out of the depths have I cried unto thee, O LORD" is right at 3–4 and is disproportionate at
1. A single number cannot express this; an interval can, at the cost of one extra small integer.

### D. Themes (47, in 8 groups)

**Definition.** What the passage is *about* — its subject matter.
**Inclusion.** Neutral, descriptive, applicable to both scriptures without theological commitment.
**Exclusion.** No emotional content (that is A), no pastoral function (that is E), no speech-act
(that is G). Themes carry **no valence**: `afterlife_punishment` is as legitimate a theme as
`divine_mercy`. Keeping themes valence-free is what allows suitability to be judged separately.

| Group | Values |
|---|---|
| Divine character & action | `divine_presence`, `divine_mercy`, `divine_power`, `divine_faithfulness`, `divine_justice`, `divine_guidance`, `divine_provision`, `divine_knowledge` |
| Human condition | `human_frailty`, `suffering_and_trial`, `sin_and_wrongdoing`, `repentance_and_return`, `doubt_and_questioning`, `mortality_and_death`, `pride_and_humility` |
| Response & practice | `trust_and_reliance`, `prayer_and_supplication`, `praise_and_thanksgiving`, `patience_and_endurance`, `obedience_and_devotion`, `remembrance_and_meditation`, `courage_and_strength`, `hope_and_expectation` |
| Relationship & community | `love_and_compassion`, `forgiveness_between_people`, `family_and_kinship`, `justice_toward_others`, `speech_and_truthfulness`, `generosity_and_charity` |
| Wisdom & conduct | `wisdom_and_discernment`, `self_restraint`, `work_and_diligence`, `wealth_and_possessions`, `contentment_and_simplicity` |
| Deliverance & restoration | `deliverance_and_rescue`, `healing_and_restoration`, `peace_and_rest`, `renewal_and_new_beginning` |
| Eschatology & consequence | `afterlife_reward`, `afterlife_punishment`, `accountability_and_reckoning`, `resurrection_and_final_day` |
| Narrative & revelation | `prophetic_narrative`, `covenant_and_law`, `revelation_and_scripture`, `creation_and_nature`, `community_history` |

47 values against QSAC's 338 and `Complete_Quran_data`'s 118. The compression is deliberate: source
vocabularies are *evidence* to be mapped in, not a target schema. Both source vocabularies fan into
these 47 via the ledger (§3), losing nothing, because the original label stays readable.

**Ambiguity notes.** `divine_justice` vs `afterlife_punishment` — the former is the attribute, the
latter the outcome; a verse may carry both. `covenant_and_law` vs `obedience_and_devotion` — the
former is the content of an obligation, the latter the disposition toward it. `suffering_and_trial`
vs `human_frailty` — affliction from outside vs limitation from within.

### E. Spiritual / reflection intents (17)

**Definition.** The pastoral act the verse can perform *for a reader*.
**Inclusion.** It must be something a person could be helped by receiving.
**Exclusion.** Not the passage's own literary function (that is G) and not the reader's state (A).

The 12 product purposes, plus 5 additions that the corpus makes necessary:

| Value | Definition | Distinguished from |
|---|---|---|
| `comfort` | Meets present pain with presence or solace | `assurance`: addresses pain, not doubt |
| `hope` | Points to future good | `encouragement`: about outcome, not effort |
| `encouragement` | Bolsters someone to keep going | `strength`: motivational, not capacitating |
| `peace` | Settles agitation | `comfort`: addresses turmoil, not pain |
| `guidance` | Says what to do, or how to see a situation | `wisdom`: situational, not general |
| `strength` | Supplies capacity to endure or act | `encouragement`: capacity, not motivation |
| `patience` | Invites endurance while an outcome is out of one's hands | `perseverance`: waiting, not effort |
| `perseverance` | Invites continued effort against resistance | `patience`: effort, not waiting |
| `gratitude` | Invites thanksgiving | `praise`: for benefit received |
| `praise` | Invites worship and adoration | `gratitude`: for who God is |
| `repentance` | Invites turning from one's own wrong | `forgiveness`: the turning |
| `forgiveness` | Concerns pardon received, or extended to another | `repentance`: the pardon |
| `wisdom` | Supplies general understanding for living | `guidance`: general, not situational |
| **`warning`** | Admonishes; announces consequence | *Added.* Without it, 3,446 judgment verses get force-fitted into `guidance`. Honest labelling is what makes honest exclusion possible |
| **`lament`** | Gives voice to pain **without resolving it** | *Added.* Psalm 88, Lamentations. A person in acute grief is often better served by a verse that names their pain than one that fixes it — a genuine pastoral act the product's list omits |
| **`assurance`** | Confirms standing, identity, or security | *Added.* The answer to `doubt` and `shame`, which `comfort` does not address |
| **`instruction`** | Didactic or legal content: how a duty is performed | *Added.* A neutral home for law and ritual, so it is not mislabelled as `guidance` |

Ambiguity: `patience` / `perseverance` overlap heavily and annotators will disagree. The rule above
(waiting vs effort) is the tie-break; where both apply, both are listed.

### F. Situations / life contexts (30)

**Definition.** The concrete life circumstance a user is in.
**Inclusion.** Nameable by the user, common enough to be a retrieval facet, and not derivable from
emotion alone.
**Exclusion.** Emotions, and anything requiring inference about the user beyond what they said.
Sparse by design — most verses will carry 0–3, many 0.

`bereavement`, `illness_own`, `illness_loved_one`, `mental_health_struggle`, `financial_hardship`,
`unemployment_or_work_stress`, `academic_pressure`, `relationship_conflict`, `marriage_difficulty`,
`parenting`, `singleness`, `betrayal_or_broken_trust`, `isolation`, `displacement_or_migration`,
`persecution_or_discrimination`, `injustice_experienced`, `major_decision`, `life_transition`,
`waiting_for_answer`, `temptation_struggle`, `addiction_struggle`, `moral_failure_aftermath`,
`caregiving_burden`, `aging`, `conflict_or_war`, `natural_disaster`, `spiritual_dryness`,
`celebration_or_milestone`, `new_beginning`, `gratitude_moment`

**Ambiguity.** `mental_health_struggle` is a *situation*, never a diagnosis, and MoodVerse must never
present scripture as treatment. Verses tagged with it inherit an automatic
`content_advisory: clinical_adjacent` and are held out of `crisis` responses unless
`crisis_safe = true`.

### G. Scripture purpose (18) — the speech-act axis

**Definition.** What the passage is *doing in its own text*. Not what it can do for a reader (E).
**Why this axis exists.** It is the strongest single predictor of context dependency and
misleading-if-isolated, and no source annotates it for either scripture.

`declaration_about_god`, `promise`, `command`, `prohibition`, `legal_ruling`, `warning_or_threat`,
`narrative_event`, `reported_speech`, `lament_or_complaint`, `praise_or_thanksgiving`,
`prayer_or_supplication`, `wisdom_saying`, `prophecy_or_oracle`, `genealogy_or_record`,
`exhortation`, `question_or_rhetorical`, `blessing_or_benediction`, `oath_or_covenant`

**`reported_speech` is safety-critical.** It is the largest single source of
misleading-if-isolated content: a verse may accurately record what an adversary, a fool, a
false comforter, or a despairing person said. Psalm 14:1 is *"The fool hath said in his heart, There
is no God"* — the isolated clause inverts the passage. 4,857 Bible verses (15.6%) contain a speech
verb, so this is a large surface. Any record with `reported_speech` must additionally carry a
`speaker_role` from {`divine`, `prophet_or_apostle`, `righteous_figure`, `narrator`,
`ordinary_person`, `adversary_or_negative_exemplar`, `unattributed`}, and
`adversary_or_negative_exemplar` or `unattributed` is a hard exclusion trigger (§6).

`promise` carries a sub-flag `promise_conditionality` ∈ {`unconditional`, `conditional`,
`addressee_specific`}. An `addressee_specific` promise made to one named person or nation
(Jeremiah 29:11 is the canonical example of the failure mode) must not be served as though it were
made to the reader; it becomes `INCLUDE_WITH_CONTEXT` at best.

### H. Context dependency

Ordinal 0–4, **plus** a closed list of typed reasons. The reasons matter more than the number: they
are what makes the score auditable, what tells the client what context to show, and what a human
reviewer can disagree with specifically.

| Level | Name | Anchor |
|---:|---|---|
| 0 | `self_contained` | Full meaning available from the verse alone |
| 1 | `lightly_dependent` | A connective or pronoun resolves trivially; meaning survives |
| 2 | `passage_dependent` | Needs 1–3 adjacent verses |
| 3 | `pericope_dependent` | Needs the surrounding unit — story, discourse, psalm, chapter |
| 4 | `frame_dependent` | Needs a frame the text does not supply: who is speaking, the historical occasion, a legal system, a prior covenant |

`dependency_reasons[]`, closed set:
`unresolved_pronoun`, `discourse_connective_opening`, `syntactic_fragment`,
`quoted_speech_unattributed`, `speaker_is_adversary_or_negative_exemplar`,
`conditional_apodosis_elsewhere`, `referent_named_earlier`, `narrative_setup_required`,
`legal_or_ritual_frame_required`, `addressee_specific`, `historical_occasion_required`,
`figurative_requires_frame`, `irony_or_rhetorical_inversion`, `partial_list_item`

`historical_occasion_required` covers *asbab al-nuzul* for the Quran and situational framing for the
Bible with one neutral term — an example of why the taxonomy is worded religion-neutrally.

---

## 3. Source-label mapping system

### 3.1 Shape: a label-level ledger, not a verse-level rewrite

The mapping is **one row per `(source, annotation_type, source_label)`**, not per verse. The whole
ledger is roughly 500 rows — 118 `Complete_Quran_data` themes + 22 emotions + 19 categories +
11 contexts + 323 QSAC tags + 4 ELQV labels — which a human can read end to end in an afternoon.
A verse-level mapping would be 125,620 rows and would be unreviewable.

The corpus is never touched. Applying the ledger to a record is a **join at read time**, so the
mapping can be revised without re-deriving anything.

```jsonc
{
  "mapping_id": "cqd.emotion.fear",
  "source": "Complete_Quran_data",
  "source_file": "quran related/Complete_Quran_data.csv",
  "source_annotation_type": "emotion",
  "source_label": "Fear",                    // verbatim, never altered
  "source_label_occurrences": 1823,
  "source_evidence_tier": "undocumented",    // see 3.4
  "targets": [
    { "axis": "expressed_affect",            // NEVER addresses_states — see 3.3
      "value": "fear",
      "relation": "broader",
      "confidence": 0.4,
      "rationale": "Source conflates dread of judgment with reverence toward God; 89% of assignments co-occur with punishment content, so the label under-determines which is meant.",
      "method": "human_reviewed" },
    { "axis": "theme", "value": "afterlife_punishment", "relation": "related",
      "confidence": 0.3,
      "rationale": "Statistical association only (1614/1823). Recorded as a weak prior, not as an assertion about any individual verse.",
      "method": "ai_assisted" }
  ],
  "evidence_verse_ids": ["quran:2:7", "quran:2:10", "quran:94:5"],
  "status": "approved",
  "taxonomy_version": "1.0.0",
  "reviewed_by": "…", "reviewed_at": "…",
  "notes": "Split candidate: reverence sense -> awe. Requires per-verse disambiguation; not resolvable at label level."
}
```

### 3.2 What every row preserves

Original label verbatim · source · source file · source annotation type · occurrence count · the
MoodVerse target(s) · relation · confidence · rationale · method · reviewer · evidence verses ·
status · taxonomy version. Nothing is destroyed, renamed, or overwritten.

**Reversibility is a tested property, both directions:**

- *Forward:* corpus + ledger → every enrichment input, reproducibly.
- *Backward:* any enrichment value → the complete list of source labels that contributed to it, with
  the source and file for each.

Both are Phase 1B test requirements (§12).

### 3.3 The direction rule (mechanically enforced)

> **A row whose `source_annotation_type` is `emotion` may target `expressed_affect`,
> `theme`, or `none`. It may never target `addressed_states`.**

This is a build-time assertion that fails the pipeline, not a guideline. It is the mechanical guard
against the §1.8 failure. `addressed_states` has **no** source-derived path into it at all — every
value on that axis is generated by the annotation layer and reviewed, for both religions equally,
which is also the primary asymmetry control (§10).

### 3.4 Evidence tiers and weights

Weight attaches to the **source**, not the label, and is used only for evidence aggregation — never
as an output score:

| Tier | Sources | Weight | Scope of authority |
|---|---|---:|---|
| `expert_human` | ELQV | 1.00 | `expressed_affect` only — the only axis it measures |
| `ontology_guided_llm` | QSAC | 0.60 | `theme`, `scripture_purpose` priors (via `types`) |
| `undocumented` | Complete_Quran_data | 0.30 | `theme`, `expressed_affect`, weak `situation` |
| `derived` | Only TCEC cols, ELQVv2 | 0.00 | **Excluded from aggregation by mechanical filter on `independent_annotation == false`** |
| `community_vote` | OpenBible cross references | 0.00 | Context only, never relevance (§7) |
| `none` | AKJV | — | Text only |

### 3.5 Handling the dirty labels without repairing the corpus

Three anomaly classes, each with a ledger mechanism rather than a data edit:

1. **Spelling variants.** `Supplication & Spiritality` / `Spiritivity`, `Worship (‘Ibadah)'` /
   `(‘Ibadah)’`, `Ethics & Morality (Akhlaak)`, `Eschological context`, `Divine decree` each get their
   own row with `relation: "variant_of"` and `variant_of_label` naming the canonical spelling, plus
   `method: "deterministic"` and a normalisation note. Both rows resolve to the same target. The
   corpus keeps the source's spelling; the ledger records the relationship. Reversible.
2. **Column bleed.** `Moral teaching context`, `Spiritual reminder` and `Revelation` appear in both
   the `category` and `context` vocabularies. Because rows are keyed on
   `(source, annotation_type, label)`, the two occurrences are separate rows and may map differently.
   Both carry `anomaly: "column_bleed_suspected"`.
3. **Non-semantic labels.** `Makki Revelation` and `Madani Revelation` map to `axis: "none"` for every
   semantic axis, with a rationale, and are routed instead to a **structural** field
   `revelation_period` on the enrichment record. Mapping to `none` is a first-class, recorded outcome —
   it is a decision, not a gap.

Singleton noise labels (`Challenge` 1, `Justice` 1, `Warning` 1, `Arrogance` 2, `Faith` 2,
`Kindness` 2) are marked `status: "quarantined"` with `confidence: 0.1`: they are preserved and
visible, contribute nothing to aggregation, and are surfaced to the human reviewer rather than
silently dropped.

### 3.6 Fan-out and fan-in

One label may target several axes (`Guidance` → theme `divine_guidance` *and* intent `guidance`), and
many labels may target one value (QSAC `Divine Mercy`, `Forgiveness of Sins`, `Allah's Compassion` all
→ `divine_mercy`). Both are normal. What is forbidden is a *silent* many-to-one: every contributing
label stays enumerated in the enrichment record's `evidence` block, so no merge is lossy.

---

## 4. Scripture enrichment schema

One record per `canonical_id`, in a separate file, joined to the corpus by id. The corpus is never
modified.

### 4.1 Illustrative record (abbreviated)

```jsonc
{
  "canonical_id": "quran:94:5",
  "religion": "quran",
  "enrichment_schema_version": "phase1-1",
  "taxonomy_version": "1.0.0",
  "pipeline_version": "1.0.0",
  "corpus_text_sha256": "…",              // drift detection against Phase 0

  "display_text_ref": {                    // resolves the 105 divergent readings + translation choice
    "original_source": "Complete_Quran_data",
    "translation_name": "Saheeh International",
    "decision": "qsac_reading_preferred_no_basmala_prefix",
    "decided_by": "human_reviewed" },

  "expressed_affect": { "primary": "hope", "secondary": ["peace"], "text_intensity": 2 },

  "addressed_states": [
    { "state": "exhaustion", "emotional_relevance": 4,
      "evidence_span": "with hardship [will be] ease" },
    { "state": "despair",    "emotional_relevance": 3, "evidence_span": "…" }
  ],
  "primary_addressed_state": "exhaustion",
  "serves_intensity": { "min": 2, "max": 4 },
  "nuance_terms": ["weariness"],

  "themes": ["suffering_and_trial", "hope_and_expectation", "divine_mercy"],
  "intents": ["comfort", "hope", "perseverance"],
  "scripture_purpose": [
    { "purpose": "promise", "promise_conditionality": "unconditional" } ],
  "situations": ["waiting_for_answer", "financial_hardship"],
  "revelation_period": "makki",           // structural, not semantic

  "standalone_usefulness": 4,
  "context_dependency": { "level": 0, "reasons": [] },
  "requires_context": false,
  "recommended_context_span": null,
  "isolation_risk": { "level": 0, "kinds": [], "explanation": null },

  "purpose_suitability": {                 // keyed by intent — extensible without migration
    "comfort":       { "score": 4, "basis": "…", "blockers": [] },
    "hope":          { "score": 4, "basis": "…", "blockers": [] },
    "perseverance":  { "score": 3, "basis": "…", "blockers": [] },
    "repentance":    { "score": 0, "basis": "…", "blockers": ["no_call_to_turning"] }
  },

  "safety": {
    "crisis_safe": true,
    "avoid_for_states": [],                // per-state veto that INCLUDE does not override
    "content_advisories": [] },

  "curation": {
    "status": "INCLUDE",
    "rule_fired": "gate4.include",
    "curation_confidence": 0.80,
    "decided_at": "…" },

  "provenance": {                          // per field group, not per record
    "context_dependency": { "method": "deterministic_rule", "rule_id": "quran.length_and_syntax.v1" },
    "addressed_states":   { "method": "ai_reviewed", "run_ids": ["r-0001","r-0002"], "model": "…" },
    "themes":             { "method": "ai_reviewed", "run_ids": ["r-0001"] },
    "purpose_suitability":{ "method": "human_reviewed", "reviewer": "…", "reviewed_at": "…" } },

  "evidence": {
    "source_labels": [
      { "source": "Complete_Quran_data", "annotation_type": "emotion", "label": "Hope",
        "mapping_id": "cqd.emotion.hope", "tier": "undocumented", "weight": 0.3 },
      { "source": "QSAC", "annotation_type": "semantic_tag", "label": "Trials through Hardship",
        "mapping_id": "qsac.tag.trials_through_hardship", "tier": "ontology_guided_llm", "weight": 0.6 } ],
    "deterministic_priors": ["quran.short_ayah", "qsac.types.concept"],
    "source_disagreements": [],
    "cross_reference_context": null },      // null for every Quran record — by design (§7)

  "review": { "state": "approved_production", "reviewer": "…", "notes": "…" },
  "model_rationale": "…",                   // AI text, kept separate from human notes
  "notes": null,                            // human text
  "phase0_data_quality": { "status": "valid", "warnings": [] }
}
```

### 4.2 Changes from the requested field list, and why

| Requested | Proposed | Reason |
|---|---|---|
| `primary emotion`, `secondary emotions` | `expressed_affect.{primary,secondary}` **and** `addressed_states[]` + `primary_addressed_state` | **The highest-value change in the design.** §1.8 shows source labels describe the text's affect, not the reader's state. Collapsing both into one field guarantees the harm the product forbids |
| `emotional intensity` | `text_intensity` + `serves_intensity{min,max}` | The verse's force and the user intensity it serves are different facts; an interval expresses fit, a scalar cannot |
| `intent` | `intents[]`, ranked | A verse routinely comforts *and* gives hope |
| `spiritual purpose` | `scripture_purpose[]` (axis G, speech-act) | "Spiritual purpose" collided with "intent". Renamed so the pastoral act (E) and the passage's own function (G) can never be conflated |
| `standalone usefulness score`, `emotional relevance score`, `context dependency score` | Kept, as ordinal 0–4; `emotional_relevance` moved **inside** each `addressed_states` entry | Relevance is conditional on a state, so a single global number is meaningless |
| `context requirement flag` | `requires_context` + `recommended_context_span{start_id,end_id,reason}` | A bare boolean does not tell the client what to render. And you may not promise context you cannot display |
| `misleading-if-isolated flag` | `isolation_risk{level 0–3, kinds[], explanation}` | A boolean loses *why*, which is the reviewable part |
| 11 flat `*_suitability` fields | one `purpose_suitability` object keyed by intent, each `{score, basis, blockers[]}` | 11 parallel scalars are unmaintainable and a 12th purpose costs a migration; a keyed object extends for free and keeps each rationale attached to its score. Stores as JSONB with a GIN index, or normalises 1:N to `verse_purpose_suitability(verse_id, intent, score, basis)` if a relational shape is preferred later |
| `curation status`, `curation confidence` | Kept, inside `curation`, plus `rule_fired` | Recording *which rule* produced the status makes every decision explainable and lets a rule change be re-run without re-annotating |
| `provenance` | Per **field group**, not per record | A record legitimately mixes deterministic, AI and human provenance across fields; one record-level value would be a lie about most of them |
| `evidence` | Kept, expanded with `source_disagreements` and `deterministic_priors` | Disagreement between the model and a source is signal, not noise, and must survive to review |
| `reviewer status` | `review{state, reviewer, notes}` with the 6-value ladder of §9 | |
| `curation notes` | `notes` (human) **and** `model_rationale` (AI), separate fields | A human note must never be mistakable for model output |
| — | **`safety{crisis_safe, avoid_for_states[], content_advisories[]}`** *(new)* | `avoid_for_states` is the negative constraint retrieval needs and has no equivalent in the requested list. It is the field that most directly prevents harm |
| — | **`display_text_ref`** *(new)* | Phase 0 recommendation 7: decide which of the 105 divergent Arabic readings and which translation is displayed, and *record the decision*, rather than letting dictionary order settle it |
| — | **`corpus_text_sha256`** *(new)* | Detects any drift between an enrichment record and the Phase 0 text it was made against |
| — | **`revelation_period`** *(new, structural)* | Gives `Makki`/`Madani` a correct home instead of forcing chronology onto a semantic axis |

**Deliberately absent: any composite "overall score".** Ranking weights belong at query time in
Phase 2, where they are visible and tunable. Baking a final score into the data silently freezes a
retrieval policy into the corpus.

---

## 5. Scoring methodology

### 5.1 The five scores are five different questions

| Score | Question | Conditional on | Property of |
|---|---|---|---|
| `emotional_relevance` | Does this verse *speak to* this user state? | a state | verse × state |
| `standalone_usefulness` | Read alone, does it make sense and land? | nothing | verse |
| `purpose_suitability` | Does it perform *this pastoral act* well? | an intent | verse × intent |
| `context_dependency` | How much surrounding text does the plain meaning need? | nothing | verse |
| `curation_confidence` | How much do we trust **the annotation record**? | nothing | *the annotation*, not the verse |

The distinctions that are easiest to collapse, and must not be:

- **relevance ≠ suitability.** `quran:2:7` has high relevance to `fear` (it is *about* dread) and
  suitability 0 for `comfort`. This pair is the product requirement, expressed numerically. Whenever
  `emotional_relevance ≥ 3` and `purpose_suitability ≤ 1`, a `blocker` is **mandatory** — the
  annotation is invalid without one. That forces the interesting case to be explained rather than
  averaged away.
- **context_dependency ≠ standalone_usefulness.** Dependency is *input* to usefulness, not the same
  thing. "And the sons of Gomer; Ashchenaz, and Riphath, and Togarmah" has dependency 0 — nothing is
  missing — and usefulness 0. Roughly 1,535 Bible verses are in this shape.
- **curation_confidence is about the record, not the verse.** A verse can be an excellent reflection
  with confidence 0.2 (annotated once, unreviewed) or a poor one with confidence 0.95. Confidence
  gates *promotion*, never *quality*.

### 5.2 Scale design: ordinal, anchored, small

**All judgement scores are integers 0–4 with named behavioural anchors. No floats.** A model asked
for 0.73 produces noise dressed as precision; a model asked to choose among five defined levels
produces a decision that can be audited, disagreed with, and measured for inter-rater agreement
(weighted Cohen's kappa on ordinal levels; undefined in any useful way on invented floats).

**`standalone_usefulness` 0–4**

| | |
|---:|---|
| 0 | `unusable_alone` — meaning unavailable: fragment, unattributed pronoun, list item |
| 1 | `weak` — parseable but flat or confusing alone: genealogy, measurement, procedural detail |
| 2 | `serviceable` — understandable; unremarkable as a reflection |
| 3 | `strong` — self-contained, carries a complete thought worth reflecting on |
| 4 | `exemplary` — self-contained, complete and memorable; works as the entire response |

**`emotional_relevance` 0–4** (per addressed state)

| | |
|---:|---|
| 0 | `none` — no bearing on the state |
| 1 | `tangential` — **shares vocabulary, not substance.** "fear" appears, but as reverence toward God |
| 2 | `related` — touches the state indirectly |
| 3 | `direct` — speaks to the state |
| 4 | `precise` — speaks to the state's specific texture |

Level 1 exists solely to give lexical-match false positives a place to be recorded as such. Without
it, keyword and embedding matches get rounded up to "related", which is how §1.8 harm reappears
through the back door.

**`purpose_suitability` 0–4** (per intent) — same shape, plus mandatory `blockers[]` under the rule
above. Blocker vocabulary is closed:
`judgment_or_threat_content`, `addressed_to_specific_party`, `conditional_promise`,
`requires_narrative_context`, `speaker_is_negative_exemplar`, `could_increase_distress`,
`implies_blame_for_suffering`, `graphic_or_disturbing_content`, `no_call_to_turning`,
`archaic_or_opaque_phrasing`, `theologically_contested`.

**`context_dependency` 0–4** — axis H of §2, with mandatory `dependency_reasons[]` at level ≥ 2.

**`isolation_risk` 0–3**

| | |
|---:|---|
| 0 | `none` |
| 1 | `mild` — loses nuance alone |
| 2 | `significant` — plausibly misread alone |
| 3 | `severe` — **the plain isolated reading contradicts the passage's meaning**: quoted adversary speech, irony, a conditional stripped of its condition |

**`curation_confidence`** — the one non-ordinal value, and it is **banded to five levels defined by
what evidence exists**, not by a model's felt certainty:

| Band | Meaning |
|---:|---|
| 0.20 | Single model pass, no independent corroboration, no human review |
| 0.40 | Single model pass agreeing with ≥1 independent source annotation **or** a deterministic prior |
| 0.60 | Two independent model passes agree, **or** one pass plus expert-tier (ELQV) agreement on `expressed_affect` |
| 0.80 | A human reviewer approved the field group |
| 0.95 | Human-approved **and** in the gold set with measured agreement |

### 5.3 Rules that keep the scores honest

1. No stored composite score. Composition happens at query time.
2. No score is arithmetically derived from another. Each is independently assessed against its own
   evidence.
3. Cross-reference votes enter **no** score (§7).
4. Scores from different provenance tiers are never averaged. Disagreement is stored, not smoothed.
5. A model's stated confidence never becomes `curation_confidence`; only the evidence bands above do.
6. Any field whose gold-set agreement (weighted kappa) is below 0.40 may not drive an automatic
   `INCLUDE`; records depending on it fall to `REVIEW_REQUIRED` until the prompt or the definition is
   fixed. **A score nobody can reproduce is not a score.**

---

## 6. Curation decision process

### 6.1 The model proposes; a deterministic cascade decides

Gemini never emits a curation status. Status is computed by an ordered rule cascade over the
enrichment fields — first match wins, and the matching rule id is stored in `curation.rule_fired`.
Consequences: the decision is reproducible, explainable to a user or a reviewer, and **changeable
by re-running the cascade over existing annotations** without re-annotating 37,338 verses.

### 6.2 The cascade

**Gate 1 — `REVIEW_REQUIRED`** (evaluated first; any one triggers)

- `curation_confidence < 0.40`
- Phase 0 `data_quality.status` ∈ {`unresolved`, `error`}
- `isolation_risk ≥ 2` **and** `standalone_usefulness ≥ 3` (the annotation contradicts itself)
- any `emotional_relevance ≥ 3` **and** `max(purpose_suitability) ≥ 3` **and** `scripture_purpose`
  contains `warning_or_threat` (relevance/suitability tension on judgment content — the §1.8 shape)
- `scripture_purpose` contains `reported_speech` and `speaker_role` is absent
- `safety.crisis_safe` is null
- two model passes differ by ≥2 ordinal levels on any score
- record carries Phase 0 warning `original_text_variant_across_sources` and no `display_text_ref`
  decision has been recorded (the 105 divergent readings)
- any field driving this record's status has gold-set kappa < 0.40

**Gate 2 — `EXCLUDE_FROM_DEFAULT_RECOMMENDATIONS`** (any one)

- `standalone_usefulness ≤ 1`
- `isolation_risk = 3`
- `context_dependency = 4`
- `scripture_purpose` is exactly {`genealogy_or_record`}
- `scripture_purpose` contains `reported_speech` with `speaker_role` ∈
  {`adversary_or_negative_exemplar`, `unattributed`}
- `max(purpose_suitability) ≤ 1` across all intents
- `content_advisories` non-empty and no intent scores ≥ 3
- `addressed_states` empty **and** `max(purpose_suitability) ≤ 2`

**Gate 3 — `INCLUDE_WITH_CONTEXT`** (all must hold)

- `context_dependency` ∈ {2, 3}
- `standalone_usefulness ≥ 2`
- `isolation_risk ≤ 2`
- some `purpose_suitability ≥ 3`
- `recommended_context_span` present **and resolvable to real canonical ids** — a hard precondition.
  You may not promise context you cannot render.

**Gate 4 — `INCLUDE`** (all must hold)

- `context_dependency ≤ 1`
- `standalone_usefulness ≥ 3`
- `isolation_risk ≤ 1`
- at least one `purpose_suitability ≥ 3`
- `safety.crisis_safe` is determined (true or false, not null)
- `curation_confidence ≥ 0.60`

**Otherwise → `REVIEW_REQUIRED`.** Default deny: nothing reaches a user by falling through.

`EXCLUDE_FROM_DEFAULT_RECOMMENDATIONS` means *excluded from emotional recommendation*, not deleted.
Those verses stay fully present and fully searchable in study, browse and reference modes. The corpus
is complete scripture; the recommendation pool is a curated subset of it.

`REVIEW_REQUIRED` is a state, not a verdict, and carries a maximum age (proposed: 90 days). Records
that age out are reported in the validation report rather than quietly persisting.

### 6.3 How the cascade covers each stated harm

| Harm to prevent | Mechanism |
|---|---|
| Semantically related but emotionally inappropriate | `emotional_relevance` and `purpose_suitability` are separate scores; a mandatory `blocker` whenever relevance ≥3 and suitability ≤1; Gate 2 `max(purpose_suitability) ≤ 1`; relevance level 1 (`tangential`) captures lexical-only matches |
| Context-dependent when displayed alone | Gate 2 `context_dependency = 4`; Gate 3 requires a **resolvable** span before any contextual verse may be served |
| Misleading when isolated | `isolation_risk`; Gate 2 at level 3; Gate 1 on self-contradiction; `reported_speech` + `speaker_role` |
| Likely to worsen the user's state | `safety.avoid_for_states[]` (per-state veto, applied at serving time, **not overridden by INCLUDE**); blockers `could_increase_distress`, `implies_blame_for_suffering`; the crisis rule below |
| Narratively important but unsuitable standalone | `standalone_usefulness` is scored independently of theme and relevance; Gate 2 at ≤1. Theological weight has no path into the decision |
| Dependent on surrounding verses | `context_dependency` + typed `dependency_reasons[]` + `recommended_context_span` |

### 6.4 Two rules that live outside the cascade

**Per-state veto.** Inclusion is global; appropriateness is per-request. `avoid_for_states[]` blocks
a verse for specific user states even when its status is `INCLUDE`. Job 1:21 ("the LORD gave, and the
LORD hath taken away") is genuinely `INCLUDE`-worthy and should carry
`avoid_for_states: [anger, despair, grief@intensity≥3]` — to a freshly bereaved person it can read as
blame.

**Crisis rule.** At user intensity 4, eligibility narrows hard: only `crisis_safe = true`, intent ∈
{`comfort`, `lament`, `assurance`, `peace`}, `isolation_risk = 0`, `context_dependency ≤ 1`. Intents
`warning`, `repentance`, `instruction` and `guidance` are hard-blocked at intensity 4. This is stated
here as a data requirement so Phase 1B stores what Phase 2 will need to enforce it.

---

## 7. Use of the cross-reference graph

### 7.1 The prohibition

> **`votes` may not appear in any enrichment field, any score, or any curation rule.**

Enforced as a Phase 1B test asserting that no enrichment field's value changes when every vote value
is permuted. Votes measure how many people liked a *link*. That is not relevance, not similarity, not
emotional fit, and not a judgement about either verse.

### 7.2 The three legitimate uses

**(a) Passage-boundary discovery — structure, not weight.** 88,130 targets are ranges naming spans
the community treats as units. If verse V falls inside many such ranges, that is evidence about the
pericope V belongs to, and it is *counting structural facts*, not weighting opinions. Yields
`passage_membership_evidence: {containing_range_count, modal_span}` as a candidate for
`recommended_context_span` — which a human or the model then confirms.

**(b) Context-dependency corroboration — shape, not weight.** A verse whose *referrers* cluster in
its immediate neighbourhood (|Δverse| ≤ 3, same chapter) behaves like part of a unit; a verse
referenced from across the canon behaves like a self-contained aphorism. The statistic is the
**dispersion of referrer distance** — edge existence and location only, never edge weight.

**(c) "See also" at display time.** Related passages may be surfaced in the UI, explicitly labelled
*OpenBible community cross-references*, in a visually separate region from the MoodVerse response, so
a community link is never mistaken for a curated recommendation.

### 7.3 Constraints

- **Bible-only asymmetry guard.** `evidence.cross_reference_context` is `null` for all 6,236 Quran
  records, and **the curation cascade may not reference it**. It may only *corroborate* a
  context-dependency assessment already made from the text — never originate one. Otherwise 31,102
  Bible verses gain a feature 6,236 Quran verses cannot have, and §10's problem inverts.
- Negative (1,243) and zero-vote (2,271) edges are retained and never filtered. A downvoted link is
  data about the community, not a defect.
- Ranges are **not** expanded into member verses. Phase 0 declined to; doing it silently in Phase 1B
  would invent verse-level claims the source never made.
- The 1,740 Bible verses with no outgoing edges are **not** low-value. Absence of edges is absence of
  evidence.
- The 4 records with unresolved `3John.1.15` targets keep their `unresolved` status and route to
  `REVIEW_REQUIRED` via Gate 1.

---

## 8. AI-assisted curation methodology (the Gemini contract)

**One sentence:** Gemini performs *interpretation and judgement over text it is given*; it never
*supplies* text, and it never *decides* status.

### 8.1 Input contract

Each request carries: the `canonical_id`; the verse text **verbatim** with its translation name and
source; a delimited context window of N preceding and N following verses, verbatim, explicitly marked
*context only — do not annotate*; book/surah and genre metadata; the deterministic priors computed for
this verse; the source annotations, if any; the closed taxonomy enums with their definitions; and the
scale anchors.

Two prompt-design decisions carry most of the quality:

1. **Source annotations are shown, but explicitly framed.** The block states: *these are third-party
   labels of varying and sometimes unknown provenance; they describe the emotion the text expresses,
   not the reader it serves; you may disagree, and if you disagree you must record it in
   `source_disagreements`.* Showing them improves grounding; framing them prevents anchoring into the
   §1.8 direction error; requiring an explicit disagreement field makes anchoring **measurable**.
2. **Both religions receive the identical template, taxonomy, scales and window size.** The only
   difference is the metadata block, which is largely empty for Bible records. This is the primary
   asymmetry control (§10).

A **blind-mode variant** withholds the source-annotation block entirely. It is run on a sample and
its output compared against the shown-mode output; that comparison is the asymmetry audit of §10.

### 8.2 Output contract

Strict JSON via `responseSchema` with every enum closed; temperature 0 (or the lowest available);
no free text outside declared string fields; every score an integer within its declared range; every
rationale ≤ 300 characters.

```jsonc
{
  "canonical_id": "bible:Psalms:34:18",
  "verse_text_sha256": "…",                 // echo of what we sent
  "taxonomy_version": "1.0.0",
  "expressed_affect": { "primary": "sadness", "secondary": ["hope"], "text_intensity": 3 },
  "addressed_states": [
    { "state": "grief", "emotional_relevance": 4,
      "evidence_span": "nigh unto them that are of a broken heart" } ],
  "themes": ["divine_presence", "suffering_and_trial"],
  "intents": ["comfort", "assurance"],
  "scripture_purpose": [{ "purpose": "declaration_about_god" }],
  "situations": ["bereavement"],
  "standalone_usefulness": 4,
  "context_dependency": { "level": 0, "reasons": [] },
  "isolation_risk": { "level": 0, "kinds": [], "explanation": null },
  "purpose_suitability": { "comfort": { "score": 4, "basis": "…", "blockers": [] } },
  "safety": { "crisis_safe": true, "avoid_for_states": [], "content_advisories": [] },
  "source_disagreements": [],
  "theologically_contested": false,
  "model_rationale": "…",
  "self_reported_uncertainty": ["situations"]   // advisory only; never becomes curation_confidence
}
```

### 8.3 Response validation — reject and retry, never repair

1. `canonical_id` echoes the request exactly.
2. `verse_text_sha256` echoes the hash of the text we sent — proves it annotated what we sent.
3. **No field contains scripture text except `evidence_span`, and every `evidence_span` is a verbatim
   substring of the supplied verse text.** A mechanically checkable, near-free hallucination detector.
4. Every enum value exists in the taxonomy version named in the request.
5. Every score is an integer in range; every ordinal is within its scale.
6. **No verse-reference pattern** (`\b\d+:\d+\b`, book names, surah numbers) appears in any free-text
   field — blocks invented citations.
7. Conditional requirements hold: `blockers` present when relevance ≥3 and suitability ≤1;
   `dependency_reasons` present when `context_dependency ≥ 2`; `speaker_role` present when
   `scripture_purpose` contains `reported_speech`; `explanation` present when `isolation_risk ≥ 2`.

On failure: write the raw response to `rejects.jsonl`, retry **once**, then mark `REVIEW_REQUIRED`.
**A malformed response is never programmatically repaired** — repair is silent reinterpretation, which
is exactly what Phase 0 refused to do and Phase 1 must not start doing.

### 8.4 What Gemini must not do

Stated as system-prompt clauses **and** enforced post hoc by the checks above:

- must not output scripture text beyond quoting a span of the supplied verse
- must not output a verse reference it was not given
- must not "correct", modernise, paraphrase or complete the supplied text
- must not become the source of scripture text under any circumstance — the corpus is the only source
- must not override verified source text; where it believes the text is wrong it sets
  `source_disagreements` and the record goes to review
- must not resolve theological disputes; where a reading is contested it sets
  `theologically_contested: true`, which routes to `REVIEW_REQUIRED`
- must not be cited as authority in any user-facing rationale
- **must not decide the curation status** — the §6 cascade does, deterministically

### 8.5 Operational design

- **One verse per request** for verse-level judgement. Batching invites cross-contamination between
  verses and makes the `evidence_span` check ambiguous.
- **Label-level mapping suggestions are batched** — that is ~500 decisions, not 37,338.
- **Recorded, not replayed.** LLM output is not bit-stable, so the *record* is the artefact. Every
  annotation stores model id and version string, prompt template id + sha256, taxonomy version,
  temperature, and request/response sha256. A re-run creates a **new** `run_id` and a reviewable diff;
  it never overwrites in place.
- **Two-pass policy:** pass 1 over everything; pass 2 (independent, same prompt, fresh session) over
  (a) the whole gold set, (b) everything Gate 1 would send to review, (c) a 10% stratified random
  sample. Agreement between passes is what earns the 0.60 confidence band.
- **Tiered rollout.** Using the priors of §1.2, the Bible partitions into roughly 4,775 high-yield
  (poetry/wisdom + epistle, non-dependent opening), 15,204 mixed, 11,123 low-yield verses. Phase 1B
  should annotate the high-yield tier plus the full Quran first (~11,000 records) to prove the
  pipeline and measure agreement before committing to the remaining ~26,000.

---

## 9. Human review and provenance model

### 9.1 Six origins, as an ordered ladder

| # | `annotation_method` | Meaning |
|---:|---|---|
| 1 | `source_derived` | Copied from a source annotation through an approved ledger row. Deterministic, reversible |
| 2 | `deterministic_rule` | Computed by a stated, versioned rule from text or metadata (connective opening, genre, verse length, QSAC tag `types`, xref shape) |
| 3 | `ai_generated` | Single model pass, unreviewed |
| 4 | `ai_reviewed` | ≥2 independent passes reconciled by rule; disagreements recorded, not smoothed |
| 5 | `human_reviewed` | A named reviewer inspected and accepted or edited it |
| 6 | `approved_production` | `human_reviewed` **and** passed the release checklist **and** assigned to a release version |

### 9.2 Rules

- **Provenance is per field group, not per record.** A record legitimately has
  `deterministic_rule` context dependency and `ai_generated` intents at the same time.
- **Monotone promotion only.** A field's method may move up the ladder; a pipeline re-run that would
  move it down writes a *proposal* to the review queue instead of overwriting. This is the single
  most important rule for preventing a re-run from erasing human work.
- **Human edits are overrides, not edits.** The AI value is retained; the human value is stored
  alongside with reviewer id and timestamp; the effective value is the highest-precedence one. Fully
  reversible — and it yields a free evaluation set, since AI-value vs human-value *is* the measured
  per-field error rate.
- **`overrides.jsonl` and `annotation_ledger.jsonl` are append-only.** Nothing human-authored is ever
  rewritten in place.

### 9.3 Review queue priority

1. Records that are `REVIEW_REQUIRED` but would otherwise be `INCLUDE` (highest user exposure).
2. Crisis-relevant records: `addressed_states` containing `despair` or `grief`, or
   `serves_intensity.max = 4`.
3. Records with `theologically_contested: true` or non-empty `source_disagreements`.
4. Low-confidence records with high retrieval frequency (fed back from Phase 2 once it exists).
5. A stratified random sample, for measurement rather than triage.

### 9.4 Gold set and measurement

A gold set of ~600 verses — 300 Bible and 300 Quran, stratified across genre, tier and curation
status — double-annotated by humans. It is used to:

- measure per-field agreement between model and human with **weighted Cohen's kappa** on the ordinals;
- **gate every prompt or model change**: a change that lowers kappa on the gold set is rejected;
- set the trust threshold of §5.3 rule 6 — a field below kappa 0.40 cannot drive automatic `INCLUDE`.

The agreement report is a published artefact. It is the honest answer to "how good is this
enrichment?", in place of a number that merely looks precise.

---

## 10. Bible/Quran asymmetry

### 10.1 The failure mode, stated precisely

If enrichment quality correlates with source-annotation density, Quran verses acquire richer themes,
more addressed states and higher confidence — and therefore win more retrieval slots — **not because
they are better answers but because they are better documented.** A user would be shown a Quran verse
for reasons that are purely an artefact of which datasets happened to be available. For a two-faith
reflection app that is both a product failure and a fairness failure, and it is the default outcome
unless it is designed against.

### 10.2 Six controls

**1. Uniform annotation path.** Every verse in both corpora goes through the identical prompt
template, taxonomy, scales and context window. **No verse acquires an enrichment field merely because
a source annotated it.** Source annotations are evidence shown to the annotator, never a shortcut
past the annotator. `addressed_states` in particular has no source-derived path at all (§3.3), which
means the axis retrieval depends on most is generated equally for both religions by construction.

**2. Confidence is source-blind, with one bounded exception.** The bands of §5.2 are defined by
*pipeline* evidence — model passes, human review, gold-set membership. The single source-dependent
band (0.60 via ELQV agreement) applies to 2,087 Quran verses only, so it is capped: **source agreement
may raise confidence by at most one band, and only on `expressed_affect`** — the one axis ELQV
actually measures. Every other axis's confidence ignores sources entirely.

**3. Blind-annotation calibration, with a pre-declared decision rule.** Annotate a stratified sample
of ~400 Quran verses twice — once with the source-annotation block, once without — and measure the
per-field delta. **If shown-mode and blind-mode differ materially (weighted kappa < 0.60, or
systematic score inflation > 0.3 ordinal levels), the source-annotation block is removed from the
prompt for all records**, and sources are then used only in the mapping ledger and for post-hoc
corroboration. This turns the asymmetry from an assumption into a measurement with the decision
committed in advance.

**4. Parity metrics as a release gate.** Per religion, track: mean score per field, `%INCLUDE`,
`%REVIEW_REQUIRED`, mean `curation_confidence`, and coverage of every (state × intent) cell. The gate:
for each of the 12 product purposes, **both religions must supply at least N verses at `INCLUDE`
status** (proposed N = 20). A failing cell triggers targeted annotation — never a lowered bar for the
scarce side.

**5. Retrieval-side neutrality, specified now.** Candidate pools are built **per religion** and merged
under a declared policy (the user's tradition, or balanced), never by one global score ranking that
would let annotation density decide the mix. This is recorded in Phase 1A because it constrains what
Phase 1B must store: per-religion rank-normalised fields, not globally normalised ones.

**6. Deterministic priors close the free part of the gap, symmetrically.** Each religion gets its own
prior set, because each has structure the other's sources do not annotate either:

| Bible priors | Quran priors |
|---|---|
| genre grouping (6 classes) | QSAC tag `types` (`ruling` 61 / `event` 68 / `entity` 45 → low standalone; `concept` 196 / `moral_trait` 55 → high) |
| discourse-connective opening (58.2% measured) | ayah length (p5 = 6 words; 450 ayat ≤6 words) |
| unbound-pronoun opening (5.9%) | surah position and length |
| speech-verb presence (15.6%) | `revelation_period` (structural, from CQD context) |
| genealogy/measurement patterns (4.9%) | Basmala-divergence flag (105 ayat) |
| verse length, chapter position | Phase 0 warning codes |
| cross-reference *shape*, corroboration only (§7.3) | *(none available — and none invented)* |

Calibration requirement: priors may shift a field by **at most ±1 ordinal level**, identically for
both religions, and every prior's measured hit rate against the gold set is published in
`prior_rules.md`. Different prior *sets* are unavoidable; different prior *influence* is not
acceptable.

**Explicitly out of scope:** closing the gap by importing a new Bible annotation dataset. That is new
scope with new provenance and licensing problems. **The enrichment layer is the equaliser**, not a
new source.

---

## 11. Enrichment file structure

```text
MoodVerse/
├── processed/                              # PHASE 0 — FROZEN. Never written by Phase 1B.
└── enrichment/                             # PHASE 1B — all new artefacts
    ├── README.md
    ├── build_enrichment.py                 # deterministic builder (replay, not re-call)
    ├── annotate.py                         # the only file that calls Gemini
    ├── schemas/
    │   ├── taxonomy.schema.json
    │   ├── mapping_ledger.schema.json
    │   ├── enrichment_record.schema.json
    │   └── gemini_response.schema.json     # doubles as the API responseSchema
    ├── taxonomy/
    │   ├── taxonomy.json                   # single source of truth, semver'd
    │   ├── definitions.md                  # defs, inclusion/exclusion, examples, ambiguities
    │   └── CHANGELOG.md
    ├── mappings/
    │   ├── label_inventory.json            # generated: every distinct source label + counts
    │   ├── source_label_ledger.json        # the reversible mapping ledger
    │   ├── quarantine.json                 # variants, singletons, column-bleed, with resolutions
    │   └── mapping_rules.md
    ├── priors/
    │   ├── deterministic_priors.jsonl      # 1 row per canonical_id, both religions
    │   └── prior_rules.md                  # each rule stated, with its measured hit rate
    ├── annotation/
    │   ├── prompts/<template_id>.md        # versioned, hashed
    │   └── runs/<run_id>/
    │       ├── run_manifest.json           # model, version, temp, template sha, taxonomy version
    │       ├── requests.jsonl
    │       ├── responses.jsonl
    │       └── rejects.jsonl
    ├── curation/
    │   ├── enrichment.jsonl                # THE enrichment layer, 1 record per canonical_id
    │   ├── decisions.jsonl                 # status + rule_fired, separable for re-runs
    │   ├── overrides.jsonl                 # human overrides, APPEND-ONLY
    │   ├── review_queue.json
    │   └── gold_set.jsonl
    ├── provenance/
    │   └── annotation_ledger.jsonl         # APPEND-ONLY audit log of every annotation event
    └── validation/
        ├── enrichment_validation_report.json
        ├── parity_report.json              # §10 asymmetry metrics
        ├── agreement_report.json           # §9.4 kappa vs gold set
        └── coverage_report.json            # (state × intent × religion) matrix
```

> **Deviation from `implementation_phases.md`.** That document shows the tree as
> `processed/enrichment/` and notes *"the exact structure may be refined during implementation."*
> This design proposes a **sibling** `enrichment/` instead, for the reason below. It is decision 7
> in §13 and needs your explicit sign-off; if you prefer the documented layout, every path in this
> section simply gains a `processed/` prefix and nothing else in the design changes.

**Why a sibling `enrichment/` rather than `processed/enrichment/`.** `processed/` is the frozen
output of a pipeline that hashes and rewrites its own directory; a sibling makes *"never modify Phase
0"* structurally obvious rather than a matter of discipline, and lets `processed/` be checked for
byte-identity independently of anything Phase 1 does. It also means a Phase 0 re-run can never
collide with Phase 1 artefacts.

**Why `decisions.jsonl` is separate from `enrichment.jsonl`.** The curation cascade will be tuned
repeatedly. Keeping decisions in their own file lets the cascade be re-run over unchanged annotations
in seconds, and makes "what changed when we tightened Gate 2?" a one-line diff.

**Why append-only for `overrides.jsonl` and `annotation_ledger.jsonl`.** These hold the only
irreplaceable content in the system: human judgement, and the audit trail.

---

## 12. Phase 1B implementation specification

### 12.1 Files to create

Exactly the tree in §11. Ordered by dependency:

1. `enrichment/taxonomy/taxonomy.json` + `definitions.md` — **first**; everything validates against it.
2. `enrichment/schemas/*.json` — generated from, and cross-checked against, the taxonomy.
3. `enrichment/mappings/label_inventory.json` — generated by scanning the corpus (no judgement).
4. `enrichment/mappings/source_label_ledger.json` + `quarantine.json` — deterministic rows first, then
   AI-suggested rows, then human review of every row before any is marked `approved`.
5. `enrichment/priors/deterministic_priors.jsonl` + `prior_rules.md` — pure functions of the corpus.
6. `enrichment/annotation/prompts/` + `annotate.py` — Gemini calls, recorded to `runs/<run_id>/`.
7. `enrichment/curation/enrichment.jsonl`, `decisions.jsonl`, `review_queue.json`, `gold_set.jsonl`.
8. `enrichment/provenance/annotation_ledger.jsonl`.
9. `enrichment/validation/*.json`.
10. `enrichment/build_enrichment.py` — assembles 1–9 into 7 and 9 deterministically.

### 12.2 Files that must never be modified

`processed/unified_scripture_corpus.jsonl` · `processed/cross_reference_graph.json` ·
`processed/qsac_ontology.json` · `processed/source_catalog.json` ·
`processed/validation_report.json` · `processed/source_mapping_report.json` ·
`processed/unresolved_records.json` · `processed/clarification.md` ·
`processed/build_unified_corpus.py` · `processed/osis_book_map.py` · `processed/_legacy/**` ·
everything under `bible related/` and `quran related/`.

Phase 1B must **hash all of the above before and after every run and fail if any digest changed** —
the same guard Phase 0 applies to the raw sources, extended to cover Phase 0's own outputs.

### 12.3 Determinism requirements

Phase 1B has a deterministic half and a recorded half, and the split must be structural:

- **Deterministic (byte-reproducible, like Phase 0):** `label_inventory`, `deterministic_priors`, the
  ledger application, the curation cascade, all validation reports, and `enrichment.jsonl` itself.
- **Recorded (not reproducible, captured once):** Gemini requests and responses.

**Replay determinism is the required property:**

> `build_enrichment.py` must be a **pure function** of
> (corpus + taxonomy + ledger + priors + recorded responses + overrides),
> producing a byte-identical `enrichment.jsonl` on every re-run **without issuing a single API call.**

Also required: stable key ordering; `ensure_ascii=False`; `separators=(",", ":")` for JSONL and
`indent=2` for JSON, matching Phase 0's conventions; atomic `.tmp` + `os.replace` writes;
`encoding="utf-8"` and `newline="\n"` on every open; explicit stdout encoding (the console here is
cp1252 and will raise `UnicodeEncodeError` on Arabic otherwise); sorted iteration over every set and
dict before emission.

### 12.4 Validation requirements

Structural:

1. Every `enrichment.jsonl` `canonical_id` exists in the corpus; no duplicates; no orphans.
2. Every enum value exists in the declared `taxonomy_version`.
3. Every ordinal is an integer within its scale; `curation_confidence` ∈ the five defined bands.
4. Every record's `corpus_text_sha256` matches the corpus text it claims to describe.
5. Conditional-requirement rules of §8.3 item 7 hold on the assembled record, not just on the response.
6. `recommended_context_span` endpoints resolve to real canonical ids in the same book/surah.

Integrity:

7. No enrichment field's value is a function of cross-reference `votes` (§7.1).
8. No ledger row maps a `source_annotation_type: emotion` label to `addresses_states` (§3.3).
9. No annotation whose `independent_annotation` is `false` contributes to any aggregate.
10. No `evidence_span` fails the verbatim-substring check.
11. No free-text field contains a verse-reference pattern.
12. Provenance is monotone: no field's method moved down the ladder since the previous run.
13. `evidence.cross_reference_context` is `null` for all 6,236 Quran records.
14. Every Phase 0 `warning` / `unresolved` record appears in `review_queue.json` or carries a recorded
    review decision.

Reporting (not pass/fail, but must be emitted): parity report (§10), agreement report (§9.4),
coverage matrix, curation-status distribution per religion, rule-firing counts per gate,
review-queue depth and age.

### 12.5 Test requirements

| # | Test |
|---:|---|
| 1 | **Corpus immutability** — SHA-256 of all 10 Phase 0 artefacts unchanged across a full run |
| 2 | **Replay determinism** — two consecutive `build_enrichment.py` runs produce byte-identical output, with zero API calls on the second |
| 3 | **Ledger round-trip forward** — corpus + ledger reproduces every enrichment input |
| 4 | **Ledger round-trip backward** — every enrichment value enumerates its contributing source labels, with source and file |
| 5 | **Direction rule** — a fixture ledger row mapping an `emotion` label to `addresses_states` fails the build |
| 6 | **Vote independence** — permuting every `votes` value leaves `enrichment.jsonl` byte-identical |
| 7 | **Derived-source exclusion** — `Only TCEC cols` and `ELQVv2` contribute zero weight to any aggregate |
| 8 | **Cascade determinism** — a fixture of ~50 hand-built records yields exactly the expected status and `rule_fired` for each |
| 9 | **Cascade coverage** — every gate has at least one passing and one failing fixture; no record can reach a status other than through a named rule |
| 10 | **Default deny** — a record with all fields null resolves to `REVIEW_REQUIRED`, never `INCLUDE` |
| 11 | **Hallucination guard** — a fixture response whose `evidence_span` is not a substring of the input is rejected, logged, and not repaired |
| 12 | **Invented-reference guard** — a fixture response containing a verse reference in a rationale is rejected |
| 13 | **Schema conformance** — every emitted record validates against `enrichment_record.schema.json` |
| 14 | **Taxonomy closure** — no value anywhere in any artefact is outside the declared taxonomy version |
| 15 | **Provenance monotonicity** — a run that would downgrade an `approved_production` field writes a review proposal and leaves the field unchanged |
| 16 | **Quran xref nullity** — all 6,236 Quran records have `cross_reference_context == null` |
| 17 | **UTF-8 safety** — the whole pipeline runs to completion with Arabic text on a cp1252 console |
| 18 | **Parity gate** — the parity report is produced and every (purpose × religion) cell below N is reported as a gap, not silently passed |

### 12.6 Expected outputs of Phase 1B

- `taxonomy.json` at `1.0.0` with all 8 axes populated and documented.
- A fully human-reviewed `source_label_ledger.json` covering **all ~500 distinct source labels**,
  including every label mapped to `none` and every quarantined variant.
- `deterministic_priors.jsonl` for all 37,338 records.
- Recorded annotation runs covering, at minimum, the first tier (~11,000 records: full Quran +
  Bible high-yield), with a stated plan and cost estimate for the remaining ~26,000.
- `enrichment.jsonl` for every annotated record; `decisions.jsonl` for every one.
- A ~600-verse gold set with measured per-field kappa.
- All validation, parity, agreement and coverage reports.
- A `clarification`-style Phase 1B report in the same register as Phase 0's: what was done, what was
  deliberately not done, and what remains unresolved.

### 12.7 Unresolved decisions

Listed in §13 — they need answers rather than implementation.

---

## 13. Decisions requiring approval

| # | Decision | Recommendation |
|---:|---|---|
| 1 | Split emotion into `expressed_affect` + `addressed_states` (§1.8, §2) | **Yes.** Highest-value change; without it the §1.8 harm is the default outcome |
| 2 | Replace 11 flat `*_suitability` fields with one intent-keyed object (§4.2) | **Yes.** Extensible without migration; normalises to a relational table later if needed |
| 3 | All judgement scores ordinal 0–4, no floats; confidence banded to 5 values (§5.2) | **Yes.** Ordinals are auditable and their agreement is measurable |
| 4 | No stored composite/overall score (§5.3) | **Yes.** Ranking policy belongs in Phase 2, visible and tunable |
| 5 | Add 5 intents beyond the product's 12: `warning`, `lament`, `assurance`, `instruction`, plus splitting `forgiveness`/`repentance` (§2E) | **Yes.** Honest labelling of judgment content is what makes honest exclusion possible; `lament` is a real pastoral act the list omits |
| 6 | 47 themes / 17 emotions / 18 scripture purposes / 30 situations — are these the right sizes? | Proposed as the balance between compactness and usefulness. **Needs your review of the actual value lists** |
| 7 | `enrichment/` as a **sibling** of `processed/`, not nested inside it (§11) — **deviates from `implementation_phases.md`**, which shows `processed/enrichment/` | **Yes**, but it is your call. Makes the Phase 0 freeze structural rather than disciplinary. Reverting costs one path prefix and changes nothing else |
| 8 | Curation status decided by a deterministic cascade, never by Gemini (§6.1) | **Yes.** Explainable, and re-tunable without re-annotating |
| 9 | Show source annotations in the prompt, framed — **or** withhold them entirely? (§8.1, §10.2) | **Show, framed, then measure with blind-mode calibration and switch to withholding if the pre-declared threshold is crossed.** Needs your agreement to the threshold: kappa < 0.60 or inflation > 0.3 levels |
| 10 | Evidence tier weights: ELQV 1.0 / QSAC 0.6 / Complete_Quran_data 0.3 / derived 0.0 (§3.4) | Proposed. The 0.3 for `Complete_Quran_data` is a judgement call about an undocumented source and is worth your explicit sign-off |
| 11 | Tiered annotation rollout: full Quran + Bible high-yield (~11,000) first, then ~26,000 (§8.5) | **Yes**, unless you want full coverage in one pass — which changes cost and time materially |
| 12 | Gold set size ~600 (300 per religion) and who annotates it | **Needs your decision.** Human annotation capacity is the binding constraint on the whole quality model |
| 13 | Parity release gate N = 20 INCLUDE verses per (purpose × religion) (§10) | Proposed; N is a product call |
| 14 | `REVIEW_REQUIRED` maximum age = 90 days (§6.2) | Proposed |
| 15 | Display decision for the 105 divergent Arabic readings, and which Quran translation is the default display text (§4.1 `display_text_ref`) | **Needs your decision.** Phase 0 deliberately left this open; it is a content decision, not an engineering one |
| 16 | Whether `EXCLUDE_FROM_DEFAULT_RECOMMENDATIONS` verses remain fully searchable in study/browse modes (§6.2) | **Recommend yes.** The corpus is complete scripture; only the recommendation pool is curated |
| 17 | Crisis-mode intent whitelist: `comfort`, `lament`, `assurance`, `peace` only (§6.4) | Proposed. This is a safety policy and deserves explicit sign-off |
| 18 | Whether a future phase may add a Bible annotation dataset, or whether enrichment stays the sole equaliser (§10.2) | **Recommend: enrichment stays the equaliser** in Phase 1; revisit later with a provenance and licence review |

---

**Phase 1A ends here.** No enrichment artefact, taxonomy file, mapping ledger, prompt, or production
code has been created. Phase 1B awaits approval of the decisions in §13.
