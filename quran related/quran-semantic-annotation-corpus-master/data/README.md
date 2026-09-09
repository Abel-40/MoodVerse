---
language:
  - ar
  - en
license: cc-by-4.0
task_categories:
  - text-classification
task_ids:
  - multi-label-classification
tags:
  - quran
  - arabic
  - nlp
  - ontology
  - semantic-annotation
  - islamic-studies
  - religion
pretty_name: QSAC — Quran Semantic Annotation Corpus
size_categories:
  - 1K<n<10K
---

# QSAC — Quran Semantic Annotation Corpus

## Dataset Description

QSAC is a multi-level semantic annotation dataset covering all 6,236 verses (ayat) of the Quran across 114 surahs (chapters). Each verse is paired with:

- Its original **Arabic text**
- The **Saheeh International English translation**
- **1–5 thematic tags** drawn from the hierarchical QSAC ontology

The ontology organises tags into a three-level hierarchy: **Domain → Category → Tag**, spanning Islamic theology, jurisprudence, ethics, eschatology, prophecy, history, and more. Annotation was performed using LLM-assisted labeling with ontology-guided prompts.

## Data Files

| File | Description |
|------|-------------|
| `qsac-dataset.csv` | Main annotated dataset (6,236 rows) |
| `qsac-ontology.json` | Full tag ontology with descriptions and keywords |

## Dataset Structure

### `qsac-dataset.csv`

```
surah,ayah,arabic,eng,tags
1,1,بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ,"In the name of Allah...",Names and Attributes of Allah|Divine Mercy
```

| Column | Type | Description |
|--------|------|-------------|
| `surah` | int | Surah number (1–114) |
| `ayah` | int | Verse number within the surah |
| `arabic` | string | Arabic text (UTF-8) |
| `eng` | string | English translation (Saheeh International) |
| `tags` | string | Pipe-delimited thematic tags |

The file has `#` comment lines at the top. Load with:

```python
import pandas as pd
df = pd.read_csv("qsac-dataset.csv", comment="#")
```

### `qsac-ontology.json`

```json
{
  "ontology_version": "1.0",
  "domains": [
    {
      "name": "Aqeedah (Islamic Creed)",
      "categories": [
        {
          "name": "Tawheed (Oneness of Allah)",
          "tags": [
            {
              "name": "Tawheed",
              "description": "...",
              "keywords": { "primary": [...], "secondary": [...] },
              "types": ["concept"]
            }
          ]
        }
      ]
    }
  ]
}
```

## Usage

```python
from datasets import load_dataset

ds = load_dataset("YOUR_USERNAME/qsac")
print(ds["train"][0])
```

Or directly:

```python
import pandas as pd, json

df = pd.read_csv("qsac-dataset.csv", comment="#")

# Explode multi-label tags
df["tag_list"] = df["tags"].str.split("|")

# Filter by a specific tag
mercy_verses = df[df["tags"].str.contains("Divine Mercy")]
print(mercy_verses[["surah", "ayah", "eng"]].head())
```

## Source Data

- Arabic text: Public domain
- English translation: Saheeh International
- Annotations: Original work by the QSAC authors

## Citation

```bibtex
@dataset{qsac2026,
  author    = {Ahmad Bilal},
  title     = {QSAC: Quran Semantic Annotation Corpus},
  year      = {2026},
  publisher = {HuggingFace},
  version   = {1.0},
  url       = {https://huggingface.co/datasets/YOUR_USERNAME/qsac}
}
```

## License

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
