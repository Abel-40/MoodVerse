# QSAC — Quran Semantic Annotation Corpus

> A multi-level semantic tagging dataset of all 6,236 Quranic verses, annotated across domains, categories, and fine-grained topics using a purpose-built ontology.

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)
[![Dataset on HuggingFace](https://img.shields.io/badge/HuggingFace-Dataset-yellow)](https://huggingface.co/datasets/ahmadbilal-dev/quran-semantic-annotation-corpus)
[![Dataset on Kaggle](https://img.shields.io/badge/Kaggle-Dataset-blue)](https://www.kaggle.com/datasets/ahmadbilal291/quran-semantic-annotation-corpus)

![QSAC Cover](qsac-cover.png)

---

## Motivation

Existing Quranic datasets provide text, translations, and transliterations — but none offer a structured, machine-readable semantic annotation layer that maps every verse to a meaningful thematic taxonomy.

This gap makes it difficult to build intelligent Islamic applications: a search engine that understands *concepts*, a chatbot that can cite contextually relevant verses, or a model trained to reason about Quranic themes. Simple keyword search breaks down quickly — the same concept (e.g., divine mercy, accountability, patience) is expressed in vastly different language across 6,236 verses.

QSAC fills this gap by providing:
- A **purpose-built ontology** with 338 fine-grained tags across 18 domains and 70 categories, each grounded with primary and secondary keywords to reduce ambiguity
- A **fully annotated dataset** where every verse is tagged, enabling downstream use without any additional labeling effort
- A **consistent annotation schema** designed for embedding-based retrieval, multi-label classification, and semantic search

---

## Overview

QSAC is an open dataset that brings structured semantic annotation to the Quran. Every verse (ayah) in all 114 surahs is tagged with 1–5 thematic labels drawn from a hierarchical ontology spanning Islamic theology, jurisprudence, ethics, eschatology, history, and more.

The annotation process used LLM-assisted labeling guided by the QSAC ontology, which defines tags with primary and secondary keyword sets to minimise ambiguity and embedding overlap.

**Key numbers (v1.0):**

| Stat | Value |
|------|-------|
| Total verses | 6,236 |
| Surahs | 114 |
| Ontology domains | 18 |
| Ontology categories | 70 |
| Unique tags | 338 |
| Total tag assignments | ~16,300 |
| Avg. tags per verse | 2.62 |
| Translation | Saheeh International |

---

## Repository Structure

```
qsac/
├── data/
│   ├── qsac-dataset.csv         # Annotated dataset — all 6,236 verses with tags
│   ├── qsac-ontology.json       # Full ontology — domains, categories, tags, keywords
│   └── README.md                # HuggingFace dataset card
├── scripts/
│   ├── stats_avg_tags.py        # Average tags per verse
│   ├── ontology_summary.py      # Ontology structure statistics
│   ├── ontology_distribution.py # Tag/category/domain frequency across the dataset
│   ├── validate_tags.py         # Find verses with tags absent from the ontology
│   ├── list_tags.py             # List all valid tag names from the ontology
│   ├── tag_collision.py         # Detect semantically overlapping tags via embeddings
│   └── README.md                # Script usage guide
├── CITATION.cff                 # Machine-readable citation metadata
├── LICENSE                      # CC BY 4.0 (data) + MIT (scripts)
└── README.md                    # This file
```

---

## Dataset Format

**File:** `data/qsac-dataset.csv`

| Column | Type | Description |
|--------|------|-------------|
| `surah` | int | Surah (chapter) number, 1–114 |
| `ayah` | int | Verse number within the surah |
| `arabic` | string | Original Arabic text (UTF-8) |
| `eng` | string | English translation (Saheeh International) |
| `tags` | string | Pipe-delimited `\|` thematic tags (1–5 per verse) |

**Example rows:**

```
surah,ayah,arabic,eng,tags
1,1,بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ,"In the name of Allah, the Entirely Merciful, the Especially Merciful.",Names and Attributes of Allah|Divine Mercy
1,5,إِيَّاكَ نَعْبُدُ وَإِيَّاكَ نَسْتَعِينُ,It is You we worship and You we ask for help.,Worship of Allah Alone|Supplication|Trust in Allah
```

The file includes attribution comment lines (prefixed `#`) before the CSV header. Skip them when loading:

```python
import pandas as pd

df = pd.read_csv("data/qsac-dataset.csv", comment="#")
print(df.shape)   # (6236, 5)
```

---

## Ontology Format

**File:** `data/qsac-ontology.json`

Three-level hierarchy: **Domain → Category → Tag**

```json
{
    "version": "1.0",
    "domains": [
        {
            "name": "Aqeedah (Islamic Creed)",
            "description": "Core doctrinal beliefs of Islam concerning Allah, unseen realities, divine decree, and the nature of faith and disbelief.",
            "categories": [
                {
                    "name": "Tawheed (Oneness of Allah)",
                    "description": "The foundational principle of monotheism in Islam — the absolute, undivided unity of Allah across all dimensions of divinity.",
                    "tags": [
                        {
                            "name": "Tawheed",
                            "description": "The indivisible oneness of Allah as the singular God, foundational to Islamic creed.",
                            "keywords": {
                                "primary": [
                                    "tawheed",
                                    "oneness of Allah",
                                    "monotheism",
                                    "unity of God",
                                    "ahad"
                                ],
                                "secondary": [
                                    "wahid",
                                    "wahdaniyyah",
                                    "one God",
                                    "undivided divinity"
                                ]
                            },
                            "types": [
                                "concept"
                            ]
                        }
                    ]
                }
            ]
        }
    ]
}
```

Each tag contains:
- **`name`** — canonical label used in the dataset
- **`description`** — human-readable definition
- **`keywords.primary`** — high-precision discriminative terms
- **`keywords.secondary`** — contextual broader associations
- **`types`** — classification (`concept`, `event`, `person`, `place`, etc.)

---

## Quick Start

```python
import pandas as pd
import json

# Load dataset
df = pd.read_csv("data/qsac-dataset.csv", comment="#")
print(df.shape)   # (6236, 5)
print(df.head())

# Load ontology
with open("data/qsac-ontology.json", encoding="utf-8") as f:
    ontology = json.load(f)

# Explore tag distribution
tag_counts = (
    df["tags"]
    .str.split("|")
    .explode()
    .value_counts()
)
print(tag_counts.head(20))
```

**HuggingFace Datasets:**

```python
from datasets import load_dataset

ds = load_dataset("YOUR_USERNAME/qsac")
print(ds["train"][0])
```

---

## Dataset Insights

### Domain Distribution

The 338 tags are organised into 18 top-level domains. Tag assignment counts across all 6,236 verses:

| Domain | Tag Assignments |
|--------|---------------:|
| Aqeedah (Islamic Creed) | 4,911 |
| Akhirah (The Hereafter) | 2,642 |
| Prophethood and Seerah | 2,431 |
| Akhlaq (Ethics and Character) | 1,042 |
| Creation and the Natural World | 848 |
| Ibadah (Worship) | 828 |
| Tazkiyah (Spiritual Purification) | 735 |
| Ilm (Knowledge and Education) | 634 |
| Da'wah (Calling to Islam) | 527 |
| Quran and Revelation | 465 |
| Mu'amalat (Social Relations) | 423 |
| Ahkam (Islamic Law) | 380 |
| Quranic Literary Features | 181 |
| Trials, Tests, and Divine Wisdom | 80 |
| Women in the Quran | 79 |
| Spiritual and Prophetic Experiences | 45 |
| Interfaith Relations and Coexistence | 33 |
| Environmental Ethics and Stewardship | 25 |

Aqeedah dominates because foundational creedal themes — divine oneness, attributes of Allah, faith and disbelief — recur across a wide range of surahs and verse types.

### Top 15 Most Frequent Tags

| Tag | Count |
|-----|------:|
| Disbelief | 786 |
| Divine Punishment | 536 |
| Divine Power | 358 |
| Reckoning | 346 |
| Divine Mercy | 310 |
| Shirk | 307 |
| Divine Knowledge | 300 |
| Musa | 285 |
| Resurrection | 282 |
| Faith | 278 |
| Tawheed | 267 |
| Role of Prophets | 266 |
| Description of Paradise | 234 |
| Divine Signs | 216 |
| Divine Justice | 199 |

Run `python3 scripts/ontology_distribution.py` to see the full tag, category, and domain distributions against your own dataset.

---

## Who Is This For?

**Researchers**
- Multi-label text classification benchmarks for Arabic and religious NLP
- Semantic similarity and embedding retrieval evaluation on Quranic text
- Comparative thematic studies across Quranic domains
- Fine-tuning language models on structured Islamic text

**AI & App Developers**
- Islamic chatbots and Q&A systems that need to retrieve contextually relevant verses
- Semantic Quran search engines (concept-based, not keyword-based)
- Tafsir and study applications with topic-based navigation
- RAG (Retrieval-Augmented Generation) pipelines over Quranic content
- Recommendation systems ("verses related to gratitude", "verses about justice")

**Educators and Islamic Content Creators**
- Structured thematic indexing of the Quran for curriculum development
- Topic-based lesson planning and content organization
- Building study tools that group verses by subject across different surahs

**Model Trainers**
- Supervised training data for Quran topic classification models
- Label schema for annotation of new translations or tafsir text
- Ontology-guided prompt engineering for Islamic LLM applications

---

## Use Cases

- **Semantic verse retrieval** — find all verses related to a concept without relying on keywords
- **Multi-label classification** — train models to predict thematic tags for unseen text
- **RAG pipelines** — use tags as structured metadata for context-aware retrieval
- **Islamic chatbots** — ground responses in tagged, citation-ready verse references
- **Ontology-guided embeddings** — use the keyword schema to improve vector representations
- **Thematic Quran explorer** — browse the Quran by domain, category, or tag

---

## Scripts

See [`scripts/README.md`](scripts/README.md) for full usage documentation of each utility script.

---

## Citation

If you use QSAC in your research or project, please cite:

```bibtex
@dataset{qsac2026,
  author    = {Ahmad Bilal},
  title     = {QSAC: Quran Semantic Annotation Corpus},
  year      = {2026},
  publisher = {GitHub / HuggingFace},
  version   = {1.0},
  url       = {https://github.com/dev-ahmadbilal/quran-semantic-annotation-corpus}
}
```

A `CITATION.cff` file is included for automatic citation support on GitHub.

---

## License

- **Dataset & Ontology:** [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
- **Scripts:** [MIT License](LICENSE)

You are free to share and adapt the material for any purpose, provided appropriate credit is given.

---

## Disclaimer

This dataset was produced through a combination of LLM-assisted annotation and human review. Like any human endeavour, it is not free from error — a verse may carry an imprecise tag, a tag boundary in the ontology may overlap, or an edge case may have been annotated inconsistently.

If you spot a mistake — whether in a verse's tags, an ontology description, or a keyword — please raise a GitHub Issue or open a Pull Request. Every correction improves the dataset for everyone, and all contributions are genuinely appreciated.

---

## Contributing

Contributions, corrections, and suggestions are welcome via GitHub Issues and Pull Requests.

Areas where community input is especially valued:
- Tag corrections or refinements for specific verses
- Ontology expansions for underrepresented topics
- Translations in additional languages
- Integration examples (notebooks, downstream models)

---

## Contact

**Ahmad Bilal**

- Website: [ahmad-bilal.vercel.app](https://ahmad-bilal.vercel.app/)
- GitHub: [github.com/dev-ahmadbilal](https://github.com/dev-ahmadbilal)
- LinkedIn: [linkedin.com/in/dev-ahmad-bilal](https://www.linkedin.com/in/dev-ahmad-bilal)
- Email: ahmadbilal.3491@gmail.com
