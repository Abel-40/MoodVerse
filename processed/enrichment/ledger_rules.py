"""Declared mapping rules from source labels into the MoodVerse taxonomy.

This module is DATA, not logic. It is the human-reviewable half of the mapping
ledger: build_ledger.py turns it into mappings/source_label_ledger.json and
checks it against mappings/label_inventory.json so no label is silently missed.

TARGET AXES a source label may map to:
    expressed_affect        the emotional register OF THE TEXT
    theme                   subject matter
    scripture_purpose_prior a weak hint about the passage's speech-act
    situation               life circumstance
    structural              non-semantic facts (revelation_period)
    none                    a recorded decision that the label carries nothing
                            for MoodVerse - a first-class outcome, not a gap

TARGET AXES a source label may NEVER map to:
    addressed_states    Nothing in any source measures which user state a verse
                        SERVES. Source emotion labels describe the text's own
                        affect: Complete_Quran_data's `Fear` co-occurs with
                        judgment content in 1614 of 1823 assignments (89%).
                        Mapping it to addressed_states would serve punishment
                        verses to frightened users.
    intent              An intent is a claim that the verse performs a pastoral
                        act well. That is a suitability judgement, and no source
                        - least of all an undocumented one - is entitled to make
                        it. Intents come from the annotation layer only.
    any *_suitability   Same reason, more directly.

Both prohibitions are asserted at build time in build_ledger.py.

REFINEMENT vs PHASE1A_DESIGN.md section 3.6: the design sketched a fan-out
example mapping `Guidance` to both theme `divine_guidance` and intent
`guidance`. On implementation that is wrong for the reason above, so the intent
half is dropped. Source labels describe content; they do not certify usefulness.

RELATION values:
    exact       the source label and the MoodVerse value denote the same thing
    broader     the source label is wider than the MoodVerse value
    narrower    the source label is narrower than the MoodVerse value
    related     conceptually adjacent, not equivalent
    partial     covers part of the source label's meaning; something is lost
    variant_of  a spelling variant of another label in the same vocabulary
    none        deliberately carries nothing across
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# ELQV - expert human tier. Four classes, 2087 verses.
# Scope is expressed_affect ONLY: the dataset measures the emotion of the verse,
# and its label set has no positive-supportive class at all (anger + fear +
# sadness = 72% of assignments), so it cannot speak to what a verse is good for.
# ---------------------------------------------------------------------------

ELQV_EMOTION = {
    "anger": [("expressed_affect", "anger", "exact", 0.9)],
    "fear": [("expressed_affect", "fear", "broader", 0.7)],
    "joy": [("expressed_affect", "joy", "exact", 0.9)],
    "sadness": [("expressed_affect", "sadness", "broader", 0.8)],
}

ELQV_RATIONALE = {
    "fear": (
        "Expert-annotated, but the class conflates dread of judgment with reverence toward "
        "God, which MoodVerse separates as `fear` and `awe`. Mapped to `fear` as the broader "
        "reading; per-verse disambiguation is left to the annotation layer."
    ),
    "sadness": (
        "Covers both loss-anchored sorrow and undifferentiated low mood, which MoodVerse "
        "separates as `grief` and `sadness`. Mapped to the broader `sadness`."
    ),
}

# ---------------------------------------------------------------------------
# Complete_Quran_data / emotion - undocumented tier, 22 values.
# Several values are not emotions (Guidance, Faith, Justice, Warning) and route
# to `theme` instead. Values occurring <= 2 times are quarantined by
# build_ledger.py regardless of what appears here.
# ---------------------------------------------------------------------------

CQD_EMOTION = {
    "Fear": [("expressed_affect", "fear", "broader", 0.4)],
    "Awe": [("expressed_affect", "awe", "exact", 0.6)],
    "Hope": [("expressed_affect", "hope", "exact", 0.6)],
    "Determination": [("theme", "courage_and_strength", "related", 0.4)],
    "Anger at Injustice": [("expressed_affect", "anger", "narrower", 0.6)],
    "Gratitude": [("expressed_affect", "gratitude", "exact", 0.6)],
    "Sadness": [("expressed_affect", "sadness", "broader", 0.5)],
    "Comfort": [("expressed_affect", "peace", "related", 0.3)],
    "Repentance": [("theme", "repentance_and_return", "exact", 0.5)],
    "Patience": [("theme", "patience_and_endurance", "exact", 0.5)],
    "Love of Allah": [("theme", "obedience_and_devotion", "related", 0.4)],
    "Joy": [("expressed_affect", "joy", "exact", 0.6)],
    "Humility": [("theme", "pride_and_humility", "exact", 0.5)],
    "Brotherhood": [("theme", "love_and_compassion", "related", 0.4)],
    "Compassion": [("theme", "love_and_compassion", "exact", 0.5)],
    "Guidance": [("theme", "divine_guidance", "exact", 0.5)],
    "Arrogance": [("theme", "pride_and_humility", "exact", 0.4)],
    "Faith": [("theme", "trust_and_reliance", "related", 0.3)],
    "Kindness": [("theme", "love_and_compassion", "exact", 0.4)],
    "Challenge": [("none", None, "none", 0.1)],
    "Justice": [("theme", "divine_justice", "exact", 0.3)],
    "Warning": [("scripture_purpose_prior", "warning_or_threat", "exact", 0.3)],
}

CQD_EMOTION_RATIONALE = {
    "Fear": (
        "Measured: 1614 of 1823 assignments (89%) fall on judgment or punishment content, so "
        "this label largely marks verses ABOUT dread rather than verses FOR the frightened. "
        "Mapped to expressed_affect only, at low confidence. It has no path to addressed_states."
    ),
    "Awe": (
        "The source's closest value to reverence. Note that Awe and Fear together are 55% of "
        "this vocabulary's assignments, so neither discriminates well."
    ),
    "Determination": (
        "A disposition, not a felt state, so it does not belong on the emotion axis. Routed to "
        "the nearest theme."
    ),
    "Anger at Injustice": (
        "Narrower than MoodVerse `anger`, which also covers anger at circumstance and at God. "
        "94% of its assignments fall on judgment content."
    ),
    "Comfort": (
        "Describes the text's consoling register, not a felt state. `peace` is the nearest "
        "affect. Deliberately NOT mapped to the intent `comfort`: that would be an "
        "undocumented source certifying pastoral suitability."
    ),
    "Repentance": "An act, not an emotion. Routed to the corresponding theme.",
    "Patience": "A virtue, not a felt state. Routed to the corresponding theme.",
    "Guidance": "Not an emotion. Routed to the corresponding theme.",
    "Faith": "Not an emotion, and doctrinal rather than experiential; a weak partial mapping.",
    "Justice": "Not an emotion. Occurs once, so quarantined regardless.",
    "Warning": "Not an emotion; it describes the passage's speech-act. Occurs once, so quarantined.",
    "Challenge": "Too vague to map. Occurs once. Recorded as carrying nothing.",
}

# ---------------------------------------------------------------------------
# Complete_Quran_data / category - 19 values, ~9 real plus spelling variants.
# ---------------------------------------------------------------------------

CQD_CATEGORY = {
    "Eschatology (Akhirah)": [
        ("theme", "resurrection_and_final_day", "broader", 0.5),
        ("theme", "accountability_and_reckoning", "broader", 0.4),
    ],
    "History & Stories (Qasas al-Anbiya)": [
        ("theme", "prophetic_narrative", "exact", 0.6),
        ("scripture_purpose_prior", "narrative_event", "related", 0.5),
    ],
    "Faith (Aqeedah)": [("theme", "trust_and_reliance", "partial", 0.3)],
    "Divine Attributes & Signs (Asma wa Sifat)": [
        ("theme", "divine_power", "broader", 0.4),
        ("theme", "divine_knowledge", "broader", 0.4),
    ],
    "Ethics & Morality (Akhlaq)": [
        ("theme", "love_and_compassion", "broader", 0.3),
        ("theme", "speech_and_truthfulness", "broader", 0.3),
    ],
    "Supplication & Spirituality (Dua, Dhikr, Tazkiyah)": [
        ("theme", "prayer_and_supplication", "broader", 0.5),
        ("theme", "remembrance_and_meditation", "broader", 0.5),
    ],
    "Worship (‘Ibadah)": [
        ("theme", "obedience_and_devotion", "broader", 0.5),
        ("theme", "praise_and_thanksgiving", "related", 0.4),
    ],
    "Law (Ahkam)": [
        ("theme", "covenant_and_law", "exact", 0.6),
        ("scripture_purpose_prior", "legal_ruling", "related", 0.5),
    ],
    "Social Relations (Mu‘amalat)": [
        ("theme", "justice_toward_others", "broader", 0.4),
        ("theme", "family_and_kinship", "broader", 0.3),
    ],
    # column bleed - these are context values sitting in the category column
    "Moral teaching context": [("scripture_purpose_prior", "exhortation", "related", 0.2)],
    "Spiritual reminder": [("scripture_purpose_prior", "exhortation", "related", 0.2)],
    "Revelation": [("theme", "revelation_and_scripture", "exact", 0.2)],
    # truncated spellings, 1 occurrence each
    "Divine Attributes & Signs": [("theme", "divine_power", "broader", 0.2)],
    "Eschatology": [("theme", "resurrection_and_final_day", "broader", 0.2)],
}

CQD_CATEGORY_RATIONALE = {
    "Faith (Aqeedah)": (
        "Aqeedah is doctrinal creed; MoodVerse themes are experiential. No clean equivalent "
        "exists, so this is a deliberately partial mapping at low confidence rather than a "
        "forced one."
    ),
    "Ethics & Morality (Akhlaq)": (
        "Far broader than any single MoodVerse theme. Fans out to the two closest, both at low "
        "confidence; the annotation layer decides per verse."
    ),
    "Moral teaching context": "Column bleed: a `context` value found in the `category` column.",
    "Spiritual reminder": "Column bleed: a `context` value found in the `category` column.",
    "Revelation": "Column bleed: appears in the category, context and theme_tag vocabularies.",
    "Divine Attributes & Signs": "Truncation of the (Asma wa Sifat) spelling; 1 occurrence.",
    "Eschatology": "Truncation of the (Akhirah) spelling; 1 occurrence.",
}

# Spelling variants: label -> canonical label in the same vocabulary. Both keep
# their own ledger row; the variant inherits the canonical's targets and is
# marked relation `variant_of`. The corpus is never edited.
CQD_CATEGORY_VARIANTS = {
    "Supplication & Spiritality (Dua, Dhikr, Tazkiyah)": "Supplication & Spirituality (Dua, Dhikr, Tazkiyah)",
    "Supplication & Spiritivity (Dua, Dhikr, Tazkiyah)": "Supplication & Spirituality (Dua, Dhikr, Tazkiyah)",
    "Ethics & Morality (Akhlaak)": "Ethics & Morality (Akhlaq)",
    "Worship (‘Ibadah)'": "Worship (‘Ibadah)",
    "Worship (‘Ibadah)’": "Worship (‘Ibadah)",
}

# ---------------------------------------------------------------------------
# Complete_Quran_data / context - 11 values mixing discourse type with
# revelation chronology. The chronology values go to a STRUCTURAL field, not to
# any semantic axis.
# ---------------------------------------------------------------------------

CQD_CONTEXT = {
    "Makki Revelation": [("structural", "revelation_period=makki", "exact", 0.7)],
    "Madani Revelation": [("structural", "revelation_period=madani", "exact", 0.7)],
    "Historical story": [("scripture_purpose_prior", "narrative_event", "exact", 0.5)],
    "Law-giving context": [("scripture_purpose_prior", "legal_ruling", "exact", 0.5)],
    "Worship guidance": [("theme", "obedience_and_devotion", "related", 0.4)],
    "Spiritual reminder": [("scripture_purpose_prior", "exhortation", "related", 0.4)],
    "Moral teaching context": [("scripture_purpose_prior", "exhortation", "related", 0.4)],
    "Eschatological context": [("theme", "resurrection_and_final_day", "related", 0.4)],
    "Eschological context": [("theme", "resurrection_and_final_day", "related", 0.4)],
    "Daily life context": [("none", None, "none", 0.2)],
    "Revelation": [("theme", "revelation_and_scripture", "exact", 0.2)],
}

CQD_CONTEXT_RATIONALE = {
    "Makki Revelation": (
        "Revelation chronology is a structural fact about the text, not a semantic or emotional "
        "one. Given its own field rather than forced onto a taxonomy axis."
    ),
    "Madani Revelation": "As Makki Revelation: structural, not semantic.",
    "Daily life context": "Too vague to carry anything. Recorded as a decision, not a gap.",
    "Eschological context": (
        "Typo for `Eschatological context`, and the MORE frequent of the two (947 vs 398), so "
        "frequency cannot identify the canonical spelling. Both map identically."
    ),
}

CQD_CONTEXT_VARIANTS = {"Eschological context": "Eschatological context"}

# ---------------------------------------------------------------------------
# Complete_Quran_data / theme_tag - 118 values.
# ---------------------------------------------------------------------------

CQD_THEME = {
    "Guidance": "divine_guidance",
    "Disbelief": "doubt_and_questioning",
    "Punishment": "afterlife_punishment",
    "Mercy": "divine_mercy",
    "Prophethood": "prophetic_narrative",
    "Faith": "trust_and_reliance",
    "Tawheed": "divine_power",
    "Accountability": "accountability_and_reckoning",
    "Power": "divine_power",
    "Misguidance": "doubt_and_questioning",
    "Lessons from history": "community_history",
    "Prophets": "prophetic_narrative",
    "Revelation": "revelation_and_scripture",
    "Fear": "afterlife_punishment",
    "Resurrection": "resurrection_and_final_day",
    "Hell": "afterlife_punishment",
    "Reward": "afterlife_reward",
    "Knowledge": "wisdom_and_discernment",
    "Wisdom": "wisdom_and_discernment",
    "Hypocrisy": "sin_and_wrongdoing",
    "Heaven": "afterlife_reward",
    "Justice": "divine_justice",
    "Nations": "community_history",
    "Gratitude": "praise_and_thanksgiving",
    "Hope": "hope_and_expectation",
    "Dua": "prayer_and_supplication",
    "Patience": "patience_and_endurance",
    "Divine Attributes & Signs": "divine_power",
    "Family": "family_and_kinship",
    "Kindness": "love_and_compassion",
    "Forgiveness": "divine_mercy",
    "Society": "justice_toward_others",
    "Prayer": "prayer_and_supplication",
    "Humility": "pride_and_humility",
    "Honesty": "speech_and_truthfulness",
    "Marriage": "family_and_kinship",
    "Zakat": "generosity_and_charity",
    "Divine Attributes": "divine_power",
    "Repentance": "repentance_and_return",
    "Orphans": "generosity_and_charity",
    "Awe": "divine_power",
    "Trade": "wealth_and_possessions",
    "Hajj": "obedience_and_devotion",
    "Worship": "obedience_and_devotion",
    "Inheritance": "wealth_and_possessions",
    "Law": "covenant_and_law",
    "Angels": "revelation_and_scripture",
    "Neighbors": "love_and_compassion",
    "Creation": "creation_and_nature",
    "Peace": "peace_and_rest",
    "Brotherhood": "love_and_compassion",
    "Death": "mortality_and_death",
    "Fasting": "obedience_and_devotion",
    "Jihad": "covenant_and_law",
    "Divine Power": "divine_power",
    "Eschatology": "resurrection_and_final_day",
    "Ethics & Morality": "love_and_compassion",
    "Comfort": "divine_mercy",
    "Dhikr": "remembrance_and_meditation",
    "Divine Decree": "divine_power",
    "Wealth": "wealth_and_possessions",
    "Obedience": "obedience_and_devotion",
    "Anger at Injustice": "justice_toward_others",
    "Miracle": "divine_power",
    "Sadness": "suffering_and_trial",
    "Trust in Allah": "trust_and_reliance",
    "Divine Command": "covenant_and_law",
    "Eternity": "resurrection_and_final_day",
    "Intercession": "accountability_and_reckoning",
    "Qur'an": "revelation_and_scripture",
    "Sacrifice": "obedience_and_devotion",
    "Truth": "speech_and_truthfulness",
    "Divine Protection": "divine_provision",
    "Divine Will": "divine_power",
    "Divine decree": "divine_power",
    "Ethics & Morality (Akhlaq)": "love_and_compassion",
    "Healing": "healing_and_restoration",
    "Humanity": "human_frailty",
    "Morality": "love_and_compassion",
    "Protection": "divine_provision",
    "Righteousness": "obedience_and_devotion",
    "Beauty": "creation_and_nature",
    "Blessings": "divine_provision",
    "Challenge": None,
    "Choice": None,
    "Covenant": "covenant_and_law",
    "Creation of Adam": "creation_and_nature",
    "Day of Judgment": "resurrection_and_final_day",
    "Deception": "sin_and_wrongdoing",
    "Disease (metaphorical)": "sin_and_wrongdoing",
    "Divine Blessings": "divine_provision",
    "Divine Judgment": "divine_justice",
    "Divine Signs": "creation_and_nature",
    "Divine Support": "divine_provision",
    "Divine Wisdom": "divine_knowledge",
    "Falsehood": "speech_and_truthfulness",
    "Greed": "wealth_and_possessions",
    "Hijrah": "community_history",
    "Human Nature": "human_frailty",
    "Joy": "praise_and_thanksgiving",
    "Judgment": "divine_justice",
    "Leadership": "justice_toward_others",
    "Life and Death": "mortality_and_death",
    "Love of Allah": "obedience_and_devotion",
    "Materialism": "wealth_and_possessions",
    "Miracles": "divine_power",
    "Moses": "prophetic_narrative",
    "Provision": "divine_provision",
    "Purification": "repentance_and_return",
    "Purity": "repentance_and_return",
    "Regret": "repentance_and_return",
    "Return to Allah": "repentance_and_return",
    "Suffering": "suffering_and_trial",
    "Temptation": "self_restraint",
    "Time": "mortality_and_death",
    "Trials": "suffering_and_trial",
    "Trustworthiness": "speech_and_truthfulness",
    "Youth": "community_history",
}

CQD_THEME_RATIONALE = {
    "Fear": (
        "In the theme column this marks passages ABOUT the fear of punishment, not passages "
        "that console the fearful. Mapped to `afterlife_punishment` for that reason. Mapping it "
        "to an emotion here would be the direction error the taxonomy exists to prevent."
    ),
    "Disbelief": (
        "Denotes rejection of faith by others, which MoodVerse has no theme for. "
        "`doubt_and_questioning` is the nearest and is imperfect - the source describes a "
        "condition the text condemns, while the MoodVerse theme describes an experience the "
        "text gives voice to."
    ),
    "Misguidance": "As Disbelief: nearest available theme, imperfect fit, low confidence.",
    "Tawheed": (
        "Divine oneness. `divine_power` is the closest available theme; MoodVerse deliberately "
        "carries no doctrinal-creed theme."
    ),
    "Awe": "In the theme column this marks the greatness being contemplated, not the feeling.",
    "Jihad": "Mapped to `covenant_and_law` as an obligation category, not to any conflict theme.",
    "Challenge": "Too vague to map. 1 occurrence.",
    "Choice": "Too vague to map. 1 occurrence.",
}

# theme_tag values whose mapping is weaker than a straight lexical match
CQD_THEME_LOW_CONFIDENCE = {
    "Disbelief", "Misguidance", "Tawheed", "Awe", "Fear", "Jihad", "Hypocrisy",
    "Faith", "Angels", "Intercession", "Youth", "Disease (metaphorical)",
}

# ---------------------------------------------------------------------------
# QSAC - ontology-guided LLM tier, 323 used tags across 70 categories.
# Tags inherit their category's theme mapping; per-tag overrides follow. This
# keeps the reviewable surface at 70 declared decisions rather than 323, while
# still emitting one ledger row per tag so nothing is hidden.
# ---------------------------------------------------------------------------

QSAC_CATEGORY_THEME = {
    "Tawheed (Oneness of Allah)": "divine_power",
    "Divine Attributes and Signs": "divine_power",
    "Belief in the Unseen (Al-Ghayb)": "revelation_and_scripture",
    "Qadr (Divine Decree)": "divine_power",
    "Faith and Disbelief": "trust_and_reliance",
    "Covenant and Testimony": "covenant_and_law",
    "Salah": "prayer_and_supplication",
    "Sawm (Fasting)": "obedience_and_devotion",
    "Zakat and Sadaqah": "generosity_and_charity",
    "Hajj and Umrah": "obedience_and_devotion",
    "Dhikr and Supplication": "remembrance_and_meditation",
    "Purification": "repentance_and_return",
    "Oaths and Vows": "covenant_and_law",
    "Virtues": "obedience_and_devotion",
    "Vices": "sin_and_wrongdoing",
    "Interpersonal Ethics": "love_and_compassion",
    "Intention and Sincerity": "obedience_and_devotion",
    "Love and Compassion": "love_and_compassion",
    "Family and Marriage": "family_and_kinship",
    "Economic Transactions": "wealth_and_possessions",
    "Social Justice": "justice_toward_others",
    "Community and Society": "justice_toward_others",
    "Inheritance and Wealth Distribution": "wealth_and_possessions",
    "Sources of Law": "covenant_and_law",
    "Halal and Haram": "covenant_and_law",
    "Criminal Law": "covenant_and_law",
    "Jihad and Defense": "covenant_and_law",
    "Governance": "justice_toward_others",
    "Heart and Soul": "repentance_and_return",
    "Repentance and Return": "repentance_and_return",
    "Spiritual Struggle": "self_restraint",
    "Closeness to Allah": "divine_presence",
    "Death and the Grave": "mortality_and_death",
    "Day of Judgment": "resurrection_and_final_day",
    "Human Reactions on the Day": "accountability_and_reckoning",
    "Signs of the Hour": "resurrection_and_final_day",
    "Paradise": "afterlife_reward",
    "Hellfire": "afterlife_punishment",
    "Reward and Punishment": "accountability_and_reckoning",
    "Nature of the Quran": "revelation_and_scripture",
    "Revelation Process": "revelation_and_scripture",
    "Recitation and Reflection": "remembrance_and_meditation",
    "Previous Scriptures": "revelation_and_scripture",
    "Prophethood (Nubuwwah)": "prophetic_narrative",
    "Stories of Prophets (Qasas al-Anbiya)": "prophetic_narrative",
    "Seerah of Prophet Muhammad": "prophetic_narrative",
    "Character of the Prophet Muhammad": "prophetic_narrative",
    "Historical Nations": "community_history",
    "Divine Address to Prophet Muhammad": "prophetic_narrative",
    "Seeking Knowledge": "wisdom_and_discernment",
    "Wisdom and Intellect": "wisdom_and_discernment",
    "Guidance and Misguidance": "divine_guidance",
    "Methods of Da'wah": "speech_and_truthfulness",
    "Obstacles to Faith": "doubt_and_questioning",
    "Truth and Falsehood": "speech_and_truthfulness",
    "Creation of the Universe": "creation_and_nature",
    "Signs in Nature": "creation_and_nature",
    "Human Nature": "human_frailty",
    "Blessings and Provisions": "divine_provision",
    "Types of Trials": "suffering_and_trial",
    "Responses to Trials": "patience_and_endurance",
    "Wisdom behind Trials": "suffering_and_trial",
    "Rhetorical Devices": None,
    "Special Verses": None,
    "Named and Notable Women": "prophetic_narrative",
    "Women's Rights and Spiritual Equality": "justice_toward_others",
    "Theology of Other Faiths": "community_history",
    "Stewardship of the Earth": "creation_and_nature",
    "Ascension and Divine Visions": "prophetic_narrative",
    "Sacred Places in the Quran": "obedience_and_devotion",
}

# Tags whose own meaning differs enough from their category to warrant an
# explicit override.
QSAC_TAG_OVERRIDE = {
    "Divine Mercy": "divine_mercy",
    "Divine Forgiveness": "divine_mercy",
    "Forgiveness of Sins": "divine_mercy",
    "Divine Justice": "divine_justice",
    "Divine Knowledge": "divine_knowledge",
    "Divine Will": "divine_power",
    "Divine Decree": "divine_power",
    "Divine Blessings": "divine_provision",
    "Divine Reward": "afterlife_reward",
    "Divine Punishment": "afterlife_punishment",
    "Lordship of Allah": "divine_power",
    "Trust in Allah": "trust_and_reliance",
    "Reliance on Allah": "trust_and_reliance",
    "Fear of Allah": "obedience_and_devotion",
    "Hope in Allah": "hope_and_expectation",
    "Patience in Hardship": "patience_and_endurance",
    "Gratitude During Prosperity": "praise_and_thanksgiving",
    "Seeking Help through Prayer": "prayer_and_supplication",
    "Despair": "doubt_and_questioning",
    "Trials through Hardship": "suffering_and_trial",
    "Trials through Prosperity": "suffering_and_trial",
    "Purification through Trials": "suffering_and_trial",
    "Return to Allah through Trials": "repentance_and_return",
    "Supplication": "prayer_and_supplication",
    "Remembrance of Allah": "remembrance_and_meditation",
    "Description of Paradise": "afterlife_reward",
    "Rewards of Paradise": "afterlife_reward",
    "Description of Hellfire": "afterlife_punishment",
    "Punishments of Hell": "afterlife_punishment",
    "Resurrection": "resurrection_and_final_day",
    "Reckoning": "accountability_and_reckoning",
    "The Hour": "resurrection_and_final_day",
    "Guidance from Allah": "divine_guidance",
    "Misguidance": "doubt_and_questioning",
    "Righteousness": "obedience_and_devotion",
    "Destroyed Nations": "community_history",
    "Rejection of Prophets": "community_history",
    "Divine Signs": "creation_and_nature",
    "Healing": "healing_and_restoration",
    "Peace": "peace_and_rest",
    "Repentance": "repentance_and_return",
    "Charity": "generosity_and_charity",
    "Orphans and the Needy": "generosity_and_charity",
    "Honesty": "speech_and_truthfulness",
    "Backbiting": "speech_and_truthfulness",
    "Slander": "speech_and_truthfulness",
    "Lying": "speech_and_truthfulness",
    "Arrogance": "pride_and_humility",
    "Humility": "pride_and_humility",
    "Pride": "pride_and_humility",
    "Greed": "wealth_and_possessions",
    "Patience": "patience_and_endurance",
    "Death": "mortality_and_death",
    "Life of this World": "wealth_and_possessions",
}

# QSAC ontology `types` that predict low standalone usefulness and high context
# dependency. Used only as a PRIOR of at most one ordinal level, never as a
# verdict. Counts across the ontology: ruling 61, event 68, entity 45.
QSAC_TYPE_PURPOSE_PRIOR = {
    "ruling": "legal_ruling",
    "event": "narrative_event",
    "entity": "narrative_event",
    "directive": "command",
    "practice": "command",
    "sign": "declaration_about_god",
    "concept": None,
    "moral_trait": None,
}
