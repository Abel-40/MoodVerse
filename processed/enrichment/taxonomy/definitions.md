# MoodVerse taxonomy - definitions

Version `1.0.0`. **Generated from `taxonomy.json` by `build_docs.py` - do not edit by hand.**

The MoodVerse controlled taxonomy. Closed, versioned, religion-neutral vocabularies used by the enrichment layer. Independent of any source dataset's terminology. Values are stable snake_case identifiers safe for use as database enums and JSON-schema enum members; display labels may change without a data migration, identifiers may not.

## The two-axis emotion rule

A felt emotional state, as a person would name it about themselves, at the granularity at which a scripture response can meaningfully differ.

> The `emotions` vocabulary is used on TWO distinct record axes and they are never interchangeable. `expressed_affect` is the emotional register OF THE TEXT - this is where every source emotion label maps. `addressed_states` is the set of user emotional states the verse is a FIT RESPONSE TO - this is what retrieval joins against, and no source dataset measures it. See mapping_rules.md for the build-time assertion that enforces the separation.

**Why:** Measured against the Phase 0 corpus: Complete_Quran_data emotion label `Fear` co-occurs with judgment/punishment content in 1614 of 1823 assignments (89%), `Sadness` in 93%, `Anger at Injustice` in 94%. Source emotion labels describe what the text expresses, not who it helps. Collapsing the two axes into one field would serve 1614 punishment verses to frightened users.

---

## A. Emotions (17)

**Inclusion criteria**

- A user could plausibly type it about themselves.
- The appropriate pastoral response differs from every other value in this list.
- It is a state, not a situation, a virtue, or a request.

**Exclusion criteria**

- Situations belong to the `situations` axis (bereavement, illness).
- Spiritual acts belong to the `intents` axis (repentance, praise).
- Virtues and dispositions are not emotional states (humility, faith, patience-as-virtue).
- Theological postures are mapped to their emotional equivalent: 'fear of God' is `awe`, never `fear`.
- Clinical diagnoses are never used. 'depression' is not a value; the situation `mental_health_struggle` plus states such as `sadness` or `despair` carry it.

| Value | Definition | Boundary |
| --- | --- | --- |
| `anxiety` | Anticipatory dread about an uncertain future. | vs `fear`: no identified present object. When an input names no object, choose `anxiety`. |
| `fear` | Fear of a present, identified threat. | vs `anxiety`: object-specific and immediate. Source labels rendered 'fear of Allah' or 'fear of the LORD' map to `awe`, NEVER here. |
| `grief` | Sorrow arising from a specific, irrecoverable loss. | vs `sadness`: has an identifiable loss. |
| `sadness` | Low mood, heaviness or discouragement without a specific loss. | vs `grief`: no locus. |
| `loneliness` | Felt absence of connection, whether human or divine. | vs `sadness`: relational in content. Note the distinct situation `isolation`, which is the circumstance rather than the feeling. |
| `anger` | Indignation - at injustice, at another person, at circumstance, or at God. | Low-intensity frustration is `anger` at intensity 1; there is no separate value for it. |
| `guilt` | Distress about something one DID. | vs `shame`: act-focused and repairable. Guilt is answered by `forgiveness` and `repentance`. |
| `shame` | Distress about what one IS. | vs `guilt`: identity-focused, and not repaired by apology. Shame is answered by `assurance`, not by `repentance`. |
| `despair` **[safety-critical]** | Hopelessness; the belief that nothing will change. | vs `sadness`: forward-looking and totalising. SAFETY-CRITICAL: records addressing `despair` are prioritised for human review and are subject to the crisis rule. |
| `exhaustion` | Depletion, burnout, weariness. | vs `sadness`: a matter of capacity, not mood. Answered by `strength` and `peace`, rarely by `encouragement`. |
| `confusion` | Not knowing what to do; decision paralysis. | vs `doubt`: practical, not spiritual. Answered by `guidance` and `wisdom`. |
| `doubt` | Uncertainty about God, about faith, or about being heard. | vs `confusion`: the object is spiritual. Answered by `assurance`, and legitimately by `lament`. |
| `gratitude` | Thankfulness seeking expression. | vs `joy`: directed at a giver. |
| `joy` | Happiness, gladness, celebration. | vs `gratitude`: undirected. |
| `awe` | Wonder and reverence before greatness; the sense of one's own smallness. | vs `fear`: not aversive. This is the correct target for every source label of the 'fear of Allah' / 'fear of the LORD' form. |
| `peace` | Settledness, calm, contentment. | RESOLUTION RULE: when an input names a desired state ('I need peace'), the desired state goes to the `intents` axis and the state the person is actually in (anxiety, exhaustion, anger) goes here. `peace` is an emotional state only when the person reports currently having it. |
| `hope` | Forward-looking expectation of good. | vs `joy`: not yet realised. |

**Documented ambiguities**

- anxiety/fear overlap in everyday speech. Rule: absent an identified object, use `anxiety`.
- guilt/shame are frequently co-reported. Rule: primary is whichever the text or user names more specifically; the other becomes secondary.
- peace as state vs peace as intent. Rule stated on the `peace` value above.
- grief/sadness. Rule: if a loss is nameable, it is `grief`.

---

## C. Intensity (1-4)

Not 1-10. A 10-point scale invites annotators - human or model - to express confidence as precision, and the differences between 6 and 7 are noise that cannot be adjudicated or measured for agreement.

`text_intensity` is the emotional force of the verse itself. `serves_intensity` is an INTERVAL {min,max} of user intensity the verse serves well, because suitability is not monotone: 'Be still, and know that I am God' fits 1-2 and reads as dismissive at 4, while 'Out of the depths have I cried unto thee' fits 3-4 and is disproportionate at 1.

| Level | Name | Anchor |
| ---: | --- | --- |
| 1 | `low` | Present in the background; the person is functioning normally. |
| 2 | `moderate` | Clearly felt and named; functioning with effort. |
| 3 | `high` | Acute and dominating; hard to function. |
| 4 | `crisis` | Overwhelming; safety-relevant. Subject to the crisis rule. |

---

## D. Themes (47)

**Inclusion criteria**

- Neutral and descriptive.
- Applicable to both scriptures without theological commitment.
- Describes subject matter, not effect on a reader.

**Exclusion criteria**

- No emotional content - that is the `emotions` axis.
- No pastoral function - that is the `intents` axis.
- No speech-act - that is the `scripture_purposes` axis.
- No valence. A theme never implies a verse is good or bad to recommend.

### Divine character and action

| Value | Definition |
| --- | --- |
| `divine_presence` | God is with, near, or accompanying. |
| `divine_mercy` | God's compassion, kindness, and pardon. |
| `divine_power` | God's sovereignty, might, and control over creation and events. |
| `divine_faithfulness` | God's steadfastness and keeping of promises. |
| `divine_justice` | God's righteousness and just dealing. *The attribute. The outcome is `afterlife_punishment` or `accountability_and_reckoning`; a verse may carry both.* |
| `divine_guidance` | Direction, light, or teaching given by God. |
| `divine_provision` | Sustenance, care, and needs met. |
| `divine_knowledge` | God sees, knows, and is aware. |

### Human condition

| Value | Definition |
| --- | --- |
| `human_frailty` | Mortality, weakness, transience, limitation. *vs `suffering_and_trial`: limitation from within, not affliction from outside.* |
| `suffering_and_trial` | Affliction, testing, hardship. |
| `sin_and_wrongdoing` | Transgression, moral failure. |
| `repentance_and_return` | Turning back, seeking pardon. |
| `doubt_and_questioning` | Lament, complaint, unanswered questions put to God. |
| `mortality_and_death` | Dying, the grave, the brevity of life. |
| `pride_and_humility` | Self-exaltation and lowliness. |

### Response and practice

| Value | Definition |
| --- | --- |
| `trust_and_reliance` | Dependence on God. |
| `prayer_and_supplication` | Asking, calling out, petition. |
| `praise_and_thanksgiving` | Worship and gratitude expressed. |
| `patience_and_endurance` | Steadfastness under duress. |
| `obedience_and_devotion` | Following commands; faithfulness in practice. *vs `covenant_and_law`: the disposition toward an obligation, not its content.* |
| `remembrance_and_meditation` | Dwelling on God; recollection. |
| `courage_and_strength` | Being strong; not fearing. |
| `hope_and_expectation` | Looking forward; awaiting deliverance. |

### Relationship and community

| Value | Definition |
| --- | --- |
| `love_and_compassion` | Love and mercy shown toward others. |
| `forgiveness_between_people` | Pardon extended or sought between persons. |
| `family_and_kinship` | Parents, children, spouses, relatives. |
| `justice_toward_others` | Fairness; defending the oppressed. |
| `speech_and_truthfulness` | The tongue, honesty, slander, testimony. |
| `generosity_and_charity` | Giving, alms, provision for the needy. |

### Wisdom and conduct

| Value | Definition |
| --- | --- |
| `wisdom_and_discernment` | Understanding, insight, sound judgement. |
| `self_restraint` | Control of appetite, anger, and desire. |
| `work_and_diligence` | Labour, effort, sloth. |
| `wealth_and_possessions` | Riches, poverty, property. |
| `contentment_and_simplicity` | Sufficiency; freedom from craving. |

### Deliverance and restoration

| Value | Definition |
| --- | --- |
| `deliverance_and_rescue` | Being saved out of danger or distress. |
| `healing_and_restoration` | Being made whole; what was broken repaired. |
| `peace_and_rest` | Stillness, safety, repose. |
| `renewal_and_new_beginning` | Starting again; being made new. |

### Eschatology and consequence

| Value | Definition |
| --- | --- |
| `afterlife_reward` | Paradise, recompense for the righteous. |
| `afterlife_punishment` | Hell, torment, recompense for the wicked. |
| `accountability_and_reckoning` | Being answerable; the weighing of deeds. |
| `resurrection_and_final_day` | The raising of the dead; the last day. |

### Narrative and revelation

| Value | Definition |
| --- | --- |
| `prophetic_narrative` | Stories of prophets and scriptural figures. |
| `covenant_and_law` | Legal, ritual, or covenantal prescription. *vs `obedience_and_devotion`: the content of an obligation, not the disposition toward it.* |
| `revelation_and_scripture` | The text speaking about itself, its sending down, or its authority. |
| `creation_and_nature` | The made world; signs in nature. |
| `community_history` | The story of a people: exile, nations, generations past. |

---

## E. Reflection intents (17)

The pastoral act the verse can perform FOR A READER.

| Value | Definition | Distinguished from | Added |
| --- | --- | --- | :---: |
| `comfort` | Meets present pain with presence or solace. | `assurance`: addresses pain, not doubt. |  |
| `hope` | Points to future good. | `encouragement`: concerns the outcome, not the effort. |  |
| `encouragement` | Bolsters someone to keep going. | `strength`: motivational, not capacitating. |  |
| `peace` | Settles agitation. | `comfort`: addresses turmoil, not pain. |  |
| `guidance` | Says what to do, or how to see a situation. | `wisdom`: situational, not general. |  |
| `strength` | Supplies capacity to endure or act. | `encouragement`: capacity, not motivation. |  |
| `patience` | Invites endurance while an outcome is out of one's hands. | `perseverance`: waiting, not effort. |  |
| `perseverance` | Invites continued effort against resistance. | `patience`: effort, not waiting. |  |
| `gratitude` | Invites thanksgiving. | `praise`: for benefit received. |  |
| `praise` | Invites worship and adoration. | `gratitude`: for who God is. |  |
| `repentance` | Invites turning from one's own wrong. | `forgiveness`: the turning. |  |
| `forgiveness` | Concerns pardon received from God, or extended to another. | `repentance`: the pardon. |  |
| `wisdom` | Supplies general understanding for living. | `guidance`: general, not situational. |  |
| `warning` | Admonishes; announces consequence. |  | yes |
| `lament` | Gives voice to pain WITHOUT resolving it. |  | yes |
| `assurance` | Confirms standing, identity, or security. |  | yes |
| `instruction` | Didactic or legal content: how a duty is performed. |  | yes |

**Intents added beyond the product's original list, and why:**

- **`warning`** - 3446 Quran ayat (55.3%) carry judgment or punishment content. Without an honest label for it, that content is force-fitted into `guidance` and becomes recommendable. Honest labelling is what makes honest exclusion possible.
- **`lament`** - Psalm 88, Lamentations, the complaint psalms. A person in acute grief is often better served by a verse that names their pain than by one that fixes it. This is a genuine pastoral act and one of the few intents safe at crisis intensity.
- **`assurance`** - The answer to `doubt` and to `shame`, neither of which `comfort` addresses. Comfort meets pain; assurance meets the question 'am I still acceptable'.
- **`instruction`** - A neutral home for law and ritual so it is not mislabelled as `guidance` and surfaced to someone seeking direction in distress.

---

## F. Situations (30)

Sparse by design. Most verses carry 0-3; many carry none. An empty list is normal and is not a gap.

| Value | Definition |
| --- | --- |
| `bereavement` | Death of someone close. |
| `illness_own` | The person's own sickness, injury or disability. |
| `illness_loved_one` | Sickness of someone close to them. |
| `mental_health_struggle` | A period of mental or emotional difficulty, named as a circumstance and never as a diagnosis. *MoodVerse must never present scripture as treatment. Verses tagged here are held out of crisis responses unless crisis_safe is true.* |
| `financial_hardship` | Debt, poverty, inability to meet needs. |
| `unemployment_or_work_stress` | Job loss, overwork, workplace pressure. |
| `academic_pressure` | Study, examinations, educational strain. |
| `relationship_conflict` | Strife with a friend, relative or colleague. |
| `marriage_difficulty` | Strain, separation or breakdown in marriage. |
| `parenting` | Raising children; concern for one's children. |
| `singleness` | Being unpartnered, whether by choice or circumstance. |
| `betrayal_or_broken_trust` | Being deceived or let down by someone trusted. |
| `isolation` | Being cut off from community or support. |
| `displacement_or_migration` | Exile, refuge, moving far from home. |
| `persecution_or_discrimination` | Being targeted for faith, identity or origin. |
| `injustice_experienced` | Being wronged without redress. |
| `major_decision` | A consequential choice to be made. |
| `life_transition` | A significant change of stage or circumstance. |
| `waiting_for_answer` | An unresolved situation whose outcome is pending. |
| `temptation_struggle` | Pull toward something the person judges wrong. |
| `addiction_struggle` | Compulsive behaviour the person wishes to stop. |
| `moral_failure_aftermath` | Living with the consequences of one's own wrong. |
| `caregiving_burden` | Sustained care for a dependent person. |
| `aging` | Growing old; declining capacity; end of life. |
| `conflict_or_war` | Armed conflict or civil violence. |
| `natural_disaster` | Earthquake, flood, famine, storm. |
| `spiritual_dryness` | A period when faith feels empty or absent. |
| `celebration_or_milestone` | A wedding, birth, achievement or festival. |
| `new_beginning` | A fresh start. |
| `gratitude_moment` | An occasion prompting thankfulness. |

---

## G. Scripture purposes (18)

What the passage is DOING in its own text - the speech-act axis.

**Why this axis exists:** It is the strongest single predictor of context dependency and of misleading-if-isolated, and no Phase 0 source annotates it for either scripture.

| Value | Definition | Context prior |
| --- | --- | --- |
| `declaration_about_god` | States who God is or what God does. | low |
| `promise` | Commits to future good. | medium |
| `command` | Instructs the hearer to do something. | medium |
| `prohibition` | Instructs the hearer not to do something. | medium |
| `legal_ruling` | Prescriptive law or ritual regulation. | high |
| `warning_or_threat` | Announces consequence for conduct. | medium |
| `narrative_event` | Recounts what happened. | high |
| `reported_speech` **[safety-critical]** | A character speaks within the text. | high |
| `lament_or_complaint` | Voiced pain or protest addressed to God. | low |
| `praise_or_thanksgiving` | Worship or thanks offered. | low |
| `prayer_or_supplication` | Petition addressed to God. | low |
| `wisdom_saying` | A proverb or aphorism. | low |
| `prophecy_or_oracle` | A declared word about what is or will be. | high |
| `genealogy_or_record` | Lists, censuses, measurements, registers. | low |
| `exhortation` | An argued appeal to act or believe. | medium |
| `question_or_rhetorical` | Poses a question, often not to be answered. | medium |
| `blessing_or_benediction` | Pronounces good upon someone. | low |
| `oath_or_covenant` | A binding undertaking or its terms. | high |

**`promise`** - An `addressee_specific` promise made to one named person or nation must never be served as though made to the reader. Such records reach INCLUDE_WITH_CONTEXT at best.

**`reported_speech`** - The single largest source of misleading-if-isolated content. A verse may accurately record what an adversary, a fool, a false comforter or a despairing person said. Psalm 14:1 reads 'The fool hath said in his heart, There is no God' - the isolated clause inverts the passage. 4857 AKJV verses (15.6%) contain a speech verb, so this surface is large.

**`genealogy_or_record`** - Low context dependency and low standalone usefulness simultaneously - nothing is missing, and nothing is there. This pair is why the two scores must stay separate.

### Subfield `promise_conditionality`

| Value | Definition |
| --- | --- |
| `unconditional` | Holds without a stated condition. |
| `conditional` | Holds only if a stated condition is met. Displaying the apodosis without the protasis is an isolation risk. |
| `addressee_specific` | Made to a named person, group or nation. Not transferable to the reader without context. |

### Subfield `speaker_role`

| Value | Definition |
| --- | --- |
| `divine` | God speaks. |
| `prophet_or_apostle` | A prophet, messenger or apostle speaks. |
| `righteous_figure` | A figure the text presents approvingly speaks. |
| `narrator` | The text's own narrating voice. |
| `ordinary_person` | An unremarkable human speaker. |
| `adversary_or_negative_exemplar` **[hard exclusion trigger]** | An opponent, a fool, a deceiver, or a figure the text presents as wrong. |
| `unattributed` **[hard exclusion trigger]** | The speaker cannot be determined from the verse alone. |

---

## H. Context dependency (0-4)

The typed reasons matter more than the number. They are what makes the level auditable, what tells the client which context to render, and what a human reviewer can disagree with specifically. `dependency_reasons` is MANDATORY at level >= 2.

| Level | Name | Anchor |
| ---: | --- | --- |
| 0 | `self_contained` | Full meaning available from the verse alone. |
| 1 | `lightly_dependent` | A connective or pronoun resolves trivially; the meaning survives isolation. |
| 2 | `passage_dependent` | Needs 1-3 adjacent verses. |
| 3 | `pericope_dependent` | Needs the surrounding unit - story, discourse, psalm, chapter. |
| 4 | `frame_dependent` | Needs a frame the text does not supply: who is speaking, the historical occasion, a legal system, a prior covenant. |

### Dependency reasons

| Value | Definition |
| --- | --- |
| `unresolved_pronoun` | A pronoun whose referent is not in the verse. |
| `discourse_connective_opening` | Opens with And, But, For, Therefore, So, Then and similar. |
| `syntactic_fragment` | Not a complete clause on its own. |
| `quoted_speech_unattributed` | Contains speech whose speaker the verse does not name. |
| `speaker_is_adversary_or_negative_exemplar` | The speaker is a figure the text presents as wrong. |
| `conditional_apodosis_elsewhere` | The 'then' clause whose 'if' lies outside the verse. |
| `referent_named_earlier` | A person, place or thing identified upstream. |
| `narrative_setup_required` | Meaning depends on preceding events. |
| `legal_or_ritual_frame_required` | Presupposes a legal or ritual system to make sense. |
| `addressee_specific` | Spoken to one named individual or nation rather than to readers generally. |
| `historical_occasion_required` | Requires the occasion of revelation or the historical situation. Covers asbab al-nuzul for the Quran and situational framing for the Bible under one neutral term. |
| `figurative_requires_frame` | A figure of speech that misleads if read literally without its frame. |
| `irony_or_rhetorical_inversion` | Says the opposite of what it means. |
| `partial_list_item` | One member of a list whose sense depends on the whole. |

---

## Scales

**Design rule.** All judgement scores are integers 0-4 with named behavioural anchors. No floats. A model asked for 0.73 produces noise dressed as precision; a model choosing among five defined levels produces a decision that can be audited, disagreed with, and measured for inter-rater agreement with weighted Cohen's kappa.

### `standalone_usefulness`

Read alone, with no surrounding text, does this verse make sense and land?

| Level | Name | Anchor |
| ---: | --- | --- |
| 0 | `unusable_alone` | Meaning unavailable: fragment, unattributed pronoun, bare list item. |
| 1 | `weak` | Parseable but flat or confusing alone: genealogy, measurement, procedural detail. |
| 2 | `serviceable` | Understandable; unremarkable as a reflection. |
| 3 | `strong` | Self-contained and carries a complete thought worth reflecting on. |
| 4 | `exemplary` | Self-contained, complete and memorable; works as the entire response. |

### `emotional_relevance`

Does this verse speak to this user state?

Conditional on: a single emotion value.

| Level | Name | Anchor |
| ---: | --- | --- |
| 0 | `none` | No bearing on the state. |
| 1 | `tangential` | Shares vocabulary, not substance. The word 'fear' appears, but as reverence toward God. **This level exists solely to give lexical and embedding false positives a place to be recorded as such. Without it they get rounded up to 'related', which is how emotionally inappropriate matches re-enter through the back door.** |
| 2 | `related` | Touches the state indirectly. |
| 3 | `direct` | Speaks to the state. |
| 4 | `precise` | Speaks to the state's specific texture. |

### `purpose_suitability`

Does this verse perform this pastoral act well?

Conditional on: a single intent value.

| Level | Name | Anchor |
| ---: | --- | --- |
| 0 | `unsuitable` | Does not perform this act at all. |
| 1 | `poor` | Could be stretched to perform it, but badly. |
| 2 | `acceptable` | Performs it adequately. |
| 3 | `good` | Performs it well. |
| 4 | `excellent` | Performs it outstandingly; a first-choice response. |

> Whenever emotional_relevance >= 3 for any state AND purpose_suitability <= 1 for a given intent, at least one blocker MUST be recorded for that intent. The annotation is invalid without one. This forces the 'relevant but unsuitable' case - the core product requirement - to be explained rather than averaged away.

### `isolation_risk`

How badly does the plain isolated reading distort the passage?

| Level | Name | Anchor |
| ---: | --- | --- |
| 0 | `none` | Reads correctly alone. |
| 1 | `mild` | Loses nuance alone. |
| 2 | `significant` | Plausibly misread alone. |
| 3 | `severe` | The plain isolated reading contradicts the passage's meaning: quoted adversary speech, irony, a conditional stripped of its condition. **[hard exclusion trigger]** |

### `curation_confidence`

How much do we trust THE ANNOTATION RECORD - not the verse.

> A verse can be an excellent reflection with confidence 0.20 (annotated once, unreviewed) or a poor one with confidence 0.95. Confidence gates promotion, never quality. A model's self-reported certainty NEVER becomes this value.

| Band | Evidence |
| ---: | --- |
| 0.2 | Single model pass, no independent corroboration, no human review. |
| 0.4 | Single model pass agreeing with at least one independent source annotation, or with a deterministic prior. |
| 0.6 | Two independent model passes agree; or one pass plus expert-tier (ELQV) agreement on expressed_affect. |
| 0.8 | A human reviewer approved the field group. |
| 0.95 | Human-approved and in the gold set with measured agreement. |

### Blockers

| Value | Definition |
| --- | --- |
| `judgment_or_threat_content` | The verse's force is admonition or threatened consequence. |
| `addressed_to_specific_party` | Spoken to a named person or nation, not to readers. |
| `conditional_promise` | The good is contingent on a condition not visible in the verse. |
| `requires_narrative_context` | Needs the surrounding story to mean anything. |
| `speaker_is_negative_exemplar` | The words are those of a figure the text presents as wrong. |
| `could_increase_distress` | Plausibly worsens the state it would be served for. |
| `implies_blame_for_suffering` | Could read as attributing the person's suffering to their fault. |
| `graphic_or_disturbing_content` | Violent or distressing imagery. |
| `no_call_to_turning` | For the repentance intent: contains no invitation to turn. |
| `archaic_or_opaque_phrasing` | The available rendering is too obscure to land. |
| `theologically_contested` | The reading is disputed; serving it asserts a position. |

### Content advisories

| Value | Definition |
| --- | --- |
| `violence` | Killing, battle, bloodshed. |
| `death` | Dying and the dead. |
| `illness` | Disease, plague, bodily affliction. |
| `judgment_or_punishment` | Condemnation or torment. |
| `sexual_content` | Sexual acts or explicit imagery. |
| `self_harm_adjacent` | Wishing for death; self-destruction. |
| `clinical_adjacent` | Touches mental health or addiction; must never read as treatment. |
| `war` | Armed conflict. |
| `persecution` | Targeted oppression. |
| `graphic_imagery` | Vivid disturbing description. |

---

## Structural vocabularies

Non-semantic descriptive fields. These carry structural facts that must not be forced onto a semantic axis.

### Annotation methods (ordered ladder)

| Rank | Method | Meaning |
| ---: | --- | --- |
| 1 | `source_derived` | Copied from a source annotation through an approved ledger row. Deterministic and reversible. |
| 2 | `deterministic_rule` | Computed by a stated, versioned rule from text or metadata. |
| 3 | `ai_generated` | Single model pass, unreviewed. |
| 4 | `ai_reviewed` | Two or more independent passes reconciled by rule; disagreements recorded, not smoothed. |
| 5 | `human_reviewed` | A named reviewer inspected and accepted or edited it. |
| 6 | `approved_production` | Human-reviewed, passed the release checklist, and assigned to a release version. |

> A field's method may move UP this ladder. A pipeline re-run that would move it down writes a proposal to the review queue instead of overwriting. This is what prevents a re-run from erasing human work.

### Curation statuses

| Status | Meaning |
| --- | --- |
| `INCLUDE` | Eligible for default emotional recommendation, subject to the per-state veto and the crisis rule. |
| `INCLUDE_WITH_CONTEXT` | Eligible only when displayed together with its recommended context span. |
| `EXCLUDE_FROM_DEFAULT_RECOMMENDATIONS` | Not offered as an emotional recommendation. NOT deleted - remains fully present and searchable in study, browse and reference modes. |
| `REVIEW_REQUIRED` | A state, not a verdict. Awaiting human judgement. Never served. Carries a maximum age after which it is reported as stale. |

### Evidence tiers

> Weight attaches to the SOURCE, not to the label, and is used only for evidence aggregation - never as an output score. Tiers and weights are decision 10 in PHASE1A_DESIGN.md.

| Tier | Weight | Sources | Justification |
| --- | ---: | --- | --- |
| `expert_human` | 1.0 | ELQV | 24 annotators holding PhDs in Quranic sciences, Hadith or Arabic linguistics, with published inclusion/exclusion criteria. Scope is limited to expressed_affect because that is the only thing the dataset measures. |
| `ontology_guided_llm` | 0.6 | QSAC | Documented method, validated against a published ontology, zero out-of-ontology tags across 16306 assignments. Machine-generated, so not human-adjudicated. |
| `undocumented` | 0.3 | Complete_Quran_data | No stated methodology, annotator or licence. Emotion vocabulary is degenerate for retrieval (Fear + Awe = 55% of assignments; Comfort 135, Patience 80, Joy 39). Contains typos, near-duplicates and demonstrable column bleed. Retained as weak evidence, never as ground truth. |
| `derived` | 0.0 | Only TCEC cols, ELQVv2 | Verified duplicates of Complete_Quran_data and ELQV respectively. Together 54657 of 156722 stored annotations (35%). Excluded from every aggregate by mechanical filter on independent_annotation == false. |
| `community_vote` | 0.0 | OpenBible Cross References | Votes measure how many people liked a LINK. Not relevance, not similarity, not a judgement about either verse. May never enter any score. |
| `none` | 0.0 | AKJV | Scripture text only; carries no annotation. |
