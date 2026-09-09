"""Generate mappings/label_inventory.json from the Phase 0 corpus.

Pure observation, zero judgement. Every distinct (source, annotation_type,
label) triple with its occurrence count, the verses that carry it, and any
anomalies that can be detected mechanically. Nothing is renamed, corrected,
merged or dropped - the inventory is the worklist the mapping ledger is built
against.

Deterministic: same corpus produces a byte-identical file.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter, defaultdict

import mv_common as mv

OUT = mv.ENRICHMENT / "mappings" / "label_inventory.json"

# Labels occurring this many times or fewer are flagged as candidate noise. They
# are NOT dropped - they are surfaced for the human reviewer to rule on.
SINGLETON_THRESHOLD = 2

# Sample verses recorded per label, so a reviewer can see the label in use.
EXAMPLES_PER_LABEL = 3

# Similarity above which two labels in the same vocabulary are reported as
# possible typo variants of each other. Calibrated against this corpus: 0.88
# catches every typo Phase 0 documented (Spiritality/Spiritivity/Spirituality,
# Akhlaak/Akhlaq, Eschological/Eschatological) plus Miracle/Miracles, and admits
# no false positives. The nearest non-variant pair, Injustice/Justice, sits at
# 0.875. Lowering this to 0.85 adds 3 false positives and finds nothing new.
NEAR_DUPLICATE_THRESHOLD = 0.88

# Annotation-type pairs whose vocabularies overlap conceptually in the source
# file, so a shared label is evidence the columns bled into each other. Declared
# rather than inferred: Phase 0 reported that Complete_Quran_data's `category`
# column holds context values ('Moral teaching context', 'Spiritual reminder',
# 'Revelation' occur in both vocabularies).
#
# Reuse between `emotion` and `theme_tag` is NOT bleed - a verse legitimately
# carries both the theme 'Fear' and the emotion 'Fear' - and is reported
# separately as cross_column_reuse, for information only.
BLEED_PRONE_PAIRS = frozenset({frozenset({"category", "context"})})


def normalize_for_comparison(value: str) -> str:
    """A comparison key used ONLY to detect near-duplicate spellings.

    Never written to any record and never displayed. Casefold, strip accents and
    non-alphanumerics so that `Worship (‘Ibadah)` / `Worship (‘Ibadah)'` /
    `Worship (‘Ibadah)’` and `Divine Decree` / `Divine decree` collapse together.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", stripped.casefold())


def build() -> dict:
    counts: dict[tuple[str, str, str], int] = Counter()
    examples: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    files: dict[tuple[str, str], str] = {}
    religions: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    independent: dict[str, bool] = {}
    records_seen = 0

    for record in mv.iter_corpus():
        records_seen += 1
        for annotation in record.get("source_annotations", []):
            source = annotation["source"]
            atype = annotation["annotation_type"]
            if atype == "verse_text":
                continue
            key = (source, atype, annotation["value"])
            occurrences = annotation.get("source_row_occurrences", 1)
            counts[key] += occurrences
            religions[key].add(record["religion"])
            files[(source, atype)] = annotation.get("source_file", "")
            independent[source] = annotation.get("independent_annotation", True)
            if len(examples[key]) < EXAMPLES_PER_LABEL:
                examples[key].append(record["canonical_id"])

    taxonomy = mv.Taxonomy()
    tier_of = mv.source_tier_map(taxonomy)

    # near-duplicate detection, within one (source, annotation_type) vocabulary
    by_vocab: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for source, atype, label in counts:
        by_vocab[(source, atype)][normalize_for_comparison(label)].append(label)

    variant_groups: dict[tuple[str, str], dict[str, list[str]]] = {}
    for vocab, buckets in by_vocab.items():
        groups = {k: sorted(v) for k, v in buckets.items() if len(v) > 1}
        if groups:
            variant_groups[vocab] = groups

    # typo variants: high string similarity within one vocabulary. Catches what
    # normalize_for_comparison cannot, because these differ by letters rather
    # than by case or punctuation.
    near_duplicates: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for vocab, buckets in sorted(by_vocab.items()):
        vocab_labels = sorted({label for members in buckets.values() for label in members})
        for i, left in enumerate(vocab_labels):
            for right in vocab_labels[i + 1:]:
                ratio = difflib.SequenceMatcher(None, left.casefold(), right.casefold()).ratio()
                if ratio >= NEAR_DUPLICATE_THRESHOLD:
                    near_duplicates[vocab].append(
                        {
                            "labels": [left, right],
                            "similarity": round(ratio, 4),
                            "occurrences": [
                                counts[(vocab[0], vocab[1], left)],
                                counts[(vocab[0], vocab[1], right)],
                            ],
                        }
                    )

    near_duplicate_labels: set[tuple[str, str, str]] = set()
    for (source, atype), pairs in near_duplicates.items():
        for pair in pairs:
            for label in pair["labels"]:
                near_duplicate_labels.add((source, atype, label))

    # A label appearing under more than one annotation_type of the same source.
    # Only bleed-prone pairs count as an anomaly; everything else is benign
    # vocabulary reuse and is reported separately.
    label_types: dict[tuple[str, str], set[str]] = defaultdict(set)
    for source, atype, label in counts:
        label_types[(source, label)].add(atype)

    column_bleed: dict[str, list[str]] = {}
    cross_column_reuse: dict[str, list[str]] = {}
    for (source, label), types in sorted(label_types.items()):
        if len(types) < 2:
            continue
        ordered = sorted(types)
        bleeds = any(
            frozenset(pair) in BLEED_PRONE_PAIRS
            for pair in ((a, b) for a in ordered for b in ordered if a < b)
        )
        (column_bleed if bleeds else cross_column_reuse)[f"{source}‖{label}"] = ordered

    bleed_labels = {
        key.split("‖", 1)[1] for key in column_bleed
    }

    labels = []
    for (source, atype, label), count in sorted(counts.items()):
        norm = normalize_for_comparison(label)
        siblings = [
            other
            for other in variant_groups.get((source, atype), {}).get(norm, [])
            if other != label
        ]
        canonical = None
        if siblings:
            # the most frequent spelling in the group is the canonical one
            group = variant_groups[(source, atype)][norm]
            canonical = max(group, key=lambda v: (counts[(source, atype, v)], v))
        anomalies = []
        if siblings:
            anomalies.append("spelling_variant_group")
        if (source, atype, label) in near_duplicate_labels:
            anomalies.append("near_duplicate_candidate")
        if count <= SINGLETON_THRESHOLD:
            anomalies.append("low_frequency")
        if f"{source}‖{label}" in column_bleed:
            anomalies.append("column_bleed_suspected")

        labels.append(
            {
                "source": source,
                "source_file": files.get((source, atype), ""),
                "annotation_type": atype,
                "label": label,
                "occurrences": count,
                "religions": sorted(religions[(source, atype, label)]),
                "evidence_tier": tier_of.get(source, "none"),
                "independent_annotation_source": independent.get(source, True),
                "comparison_key": norm,
                "spelling_variants": siblings,
                "canonical_spelling": canonical if siblings else None,
                "anomalies": anomalies,
                "example_verses": examples[(source, atype, label)],
            }
        )

    vocab_summary = []
    for (source, atype) in sorted(files):
        rows = [l for l in labels if l["source"] == source and l["annotation_type"] == atype]
        vocab_summary.append(
            {
                "source": source,
                "annotation_type": atype,
                "distinct_labels": len(rows),
                "assignments": sum(r["occurrences"] for r in rows),
                "evidence_tier": tier_of.get(source, "none"),
                "independent_annotation_source": independent.get(source, True),
                "labels_with_anomalies": sum(1 for r in rows if r["anomalies"]),
            }
        )

    independent_labels = [l for l in labels if l["independent_annotation_source"]]

    return {
        "label_inventory_version": "1.0.0",
        "generated_by": "processed/enrichment/build_label_inventory.py",
        "taxonomy_version": taxonomy.version,
        "policy": (
            "Observation only. No label is renamed, corrected, merged or dropped here. "
            "Anomalies are reported for the mapping ledger to resolve, exactly as Phase 0 "
            "reported them without repair."
        ),
        "corpus_records_scanned": records_seen,
        "totals": {
            "distinct_labels_all_sources": len(labels),
            "distinct_labels_independent_sources": len(independent_labels),
            "vocabularies": len(vocab_summary),
            "labels_needing_ledger_rows": len(independent_labels),
        },
        "vocabularies": vocab_summary,
        "anomaly_summary": {
            "spelling_variant_groups": {
                f"{src}‖{atype}": groups for (src, atype), groups in sorted(variant_groups.items())
            },
            "near_duplicate_threshold": NEAR_DUPLICATE_THRESHOLD,
            "near_duplicate_pairs": {
                f"{src}‖{atype}": pairs for (src, atype), pairs in sorted(near_duplicates.items())
            },
            "column_bleed_suspected": dict(sorted(column_bleed.items())),
            "column_bleed_prone_pairs": [sorted(pair) for pair in sorted(map(sorted, BLEED_PRONE_PAIRS))],
            "cross_column_reuse": dict(sorted(cross_column_reuse.items())),
            "cross_column_reuse_note": (
                "Not an anomaly. The same word used in two columns of one source, e.g. "
                "Complete_Quran_data uses 'Fear' as both a theme_tag and an emotion. Reported "
                "so the ledger can map the two occurrences independently - they are separate "
                "rows keyed on (source, annotation_type, label)."
            ),
            "low_frequency_threshold": SINGLETON_THRESHOLD,
            "low_frequency_labels": sum(1 for l in labels if "low_frequency" in l["anomalies"]),
        },
        "labels": labels,
    }


def main() -> int:
    mv.setup_stdout()
    before = mv.phase0_digests()
    inventory = build()
    mv.write_json(OUT, inventory)
    mv.assert_phase0_unchanged(before, mv.phase0_digests())

    print(f"label inventory -> {OUT.relative_to(mv.BASE)}")
    print(f"  records scanned      {inventory['corpus_records_scanned']:,}")
    print(f"  distinct labels      {inventory['totals']['distinct_labels_all_sources']:,}")
    print(f"  independent sources  {inventory['totals']['distinct_labels_independent_sources']:,}"
          "  <- these need ledger rows")
    print(f"  vocabularies         {inventory['totals']['vocabularies']}")
    anomalies = inventory["anomaly_summary"]
    print(f"  variant groups       {sum(len(g) for g in anomalies['spelling_variant_groups'].values())}")
    print(f"  near-dup pairs       {sum(len(p) for p in anomalies['near_duplicate_pairs'].values())}")
    print(f"  column bleed labels  {len(anomalies['column_bleed_suspected'])}")
    print(f"  cross-column reuse   {len(anomalies['cross_column_reuse'])}  (benign)")
    print(f"  low-frequency labels {anomalies['low_frequency_labels']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
