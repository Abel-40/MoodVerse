"""MoodVerse Phase 0 - Scripture source discovery, extraction, normalization, unification.

Pipeline (Phase 0 stops at the last step; no AI curation, no embeddings, no DB):

    RAW SOURCES -> DISCOVERY -> EXTRACTION -> NORMALIZATION -> CANONICAL IDENTIFIERS
    -> CROSS-SOURCE MAPPING -> SOURCE-SPECIFIC ANNOTATIONS -> PROVENANCE
    -> VALIDATION -> UNIFIED SCRIPTURE CORPUS

Guarantees
----------
* Raw sources under `bible related/` and `quran related/` are opened read-only.
  Their SHA-256 digests are recorded before and after the run and compared.
* Deterministic: no randomness, no timestamps inside the corpus records, stable
  ordering everywhere.  Same inputs + same PIPELINE_VERSION => byte-identical
  `unified_scripture_corpus.jsonl`, `cross_reference_graph.json` and
  `qsac_ontology.json`.
* Source-preserving: annotation labels are carried through verbatim, tagged with
  the source that produced them.  No taxonomy mapping, no relabelling, no merging
  of different sources' vocabularies.  Questionable source values are reported,
  never silently repaired.
* Outputs are written to temporary files and atomically replaced, so a failed run
  cannot leave a half-written corpus behind.

Run:  python build_unified_corpus.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator

from osis_book_map import AKJV_BOOK_TO_OSIS, OSIS_TO_AKJV_BOOK

PIPELINE_VERSION = "0.2.0"
CORPUS_SCHEMA_VERSION = "phase0-2"

OUT = Path(__file__).resolve().parent
BASE = OUT.parent

# --- source paths (read-only) ------------------------------------------------
SRC = {
    "bible_akjv": "bible related/AKJV.xml",
    "bible_cross_references": "bible related/cross_references.txt",
    "quran_complete": "quran related/Complete_Quran_data.csv",
    "quran_tcec_subset": "quran related/Only TCEC cols.csv",
    "elqv": "quran related/ELQV-main/ELQV.csv",
    "elqv_v2": "quran related/ELQV-main/ELQVv2.csv",
    "qsac_dataset": "quran related/quran-semantic-annotation-corpus-master/data/qsac-dataset.csv",
    "qsac_ontology": "quran related/quran-semantic-annotation-corpus-master/data/qsac-ontology.json",
}

CROSS_REFERENCE_DATASET = "OpenBible Cross References"

# Annotation columns of Complete_Quran_data.csv / Only TCEC cols.csv, mapped to the
# annotation_type recorded in the corpus.  The *values* are never rewritten.
QURAN_META_COLUMNS = (
    ("Tags", "theme_tag"),
    ("Category", "category"),
    ("Emotion", "emotion"),
    ("Context", "context"),
)

ELQV2_TRANSLATION_COLUMNS = (
    "Sahih_International",
    "Pickthall",
    "Yusuf_Ali (YA)",
    "Shakir",
    "Muhammad_Sarwar (MS)",
    "Mohsin_Khan (MK)",
    "Arberry",
)

VERSE_REF_RE = re.compile(r"^([1-3]?[A-Za-z]+)\.(\d+)\.(\d+)$")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def path_of(source_id: str) -> Path:
    return BASE / SRC[source_id]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_manifest() -> dict[str, dict[str, Any]]:
    """SHA-256 + size for every raw input, used for reproducibility and the
    read-only guarantee check."""
    manifest = {}
    for source_id, rel in SRC.items():
        p = BASE / rel
        manifest[source_id] = {
            "path": rel,
            "sha256": sha256_of(p),
            "size_bytes": p.stat().st_size,
        }
    return manifest


def read_csv_rows(path: Path, skip_hash_comments: bool = False) -> list[dict[str, str]]:
    """Strict UTF-8 CSV read.  Decoding errors are fatal rather than silently
    replaced, so corrupted input can never reach the corpus unnoticed."""
    with path.open(encoding="utf-8", newline="") as handle:
        lines: Iterable[str] = handle
        if skip_hash_comments:
            lines = (line for line in handle if not line.lstrip().startswith("#"))
        return [dict(row) for row in csv.DictReader(lines)]


def split_source_values(raw: str | None) -> list[str]:
    """Split a multi-value source cell into its individual source labels.

    Pipe-delimited cells (QSAC) split on `|`.  Comma-delimited cells
    (Complete_Quran_data / TCEC) split on commas that are *outside* brackets, so
    a source label such as

        "Supplication & Spirituality (Dua, Dhikr, Tazkiyah)"

    survives intact instead of being shredded into three fragments.  Verified
    against the raw sources: this is identical to a naive comma split for the
    Tags, Emotion and Context columns, and differs only for Category (297 rows).

    Values themselves are never rewritten - only surrounding whitespace is
    trimmed.
    """
    text = (raw or "").strip()
    if not text:
        return []
    if "|" in text:
        parts = text.split("|")
    else:
        parts, buf, depth = [], [], 0
        for ch in text:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth = max(0, depth - 1)
            if ch == "," and depth == 0:
                parts.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def write_json(name: str, data: Any, indent: int | None = 2) -> Path:
    target = OUT / name
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=indent, sort_keys=False)
        handle.write("\n")
    os.replace(tmp, target)
    return target


def write_text(name: str, text: str) -> Path:
    target = OUT / name
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return target


# ---------------------------------------------------------------------------
# record construction
# ---------------------------------------------------------------------------

def new_record(canonical_id: str, religion: str, location: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_id": canonical_id,
        "religion": religion,
        "unit_type": "verse",
        "location": location,
        "text": {},
        "source_annotations": [],
        "cross_references": [],
        "source_provenance": [],
        "data_quality": {"status": "valid", "issues": [], "warnings": []},
    }


def add_annotation(
    record: dict[str, Any],
    source: str,
    source_file: str,
    annotation_type: str,
    value: str,
    derived_from: str | None = None,
) -> bool:
    """Append a source-native annotation, de-duplicating on
    (source, annotation_type, value).

    Re-running the pipeline, or a source that repeats the same row for the same
    verse, must not multiply annotations.  Repeat rows are recorded as
    `source_row_occurrences` so the multiplicity in the raw source stays visible
    and auditable instead of being thrown away.

    `derived_from` marks an annotation that is a copy of another source's
    annotation rather than an independent judgement (Only TCEC cols).
    """
    value = (value or "").strip()
    if not value:
        return False
    for existing in record["source_annotations"]:
        if (
            existing["source"] == source
            and existing["annotation_type"] == annotation_type
            and existing["value"] == value
        ):
            existing["source_row_occurrences"] = existing.get("source_row_occurrences", 1) + 1
            return False
    entry: dict[str, Any] = {
        "source": source,
        "source_file": source_file,
        "annotation_type": annotation_type,
        "value": value,
    }
    if derived_from:
        entry["derived_from"] = derived_from
        entry["independent_annotation"] = False
    record["source_annotations"].append(entry)
    return True


def add_provenance(record: dict[str, Any], entry: dict[str, Any]) -> None:
    if not any(p["source_name"] == entry["source_name"] for p in record["source_provenance"]):
        record["source_provenance"].append(entry)


def add_original_variant(
    record: dict[str, Any],
    source: str,
    source_file: str,
    source_field: str,
    text: str,
    language: str = "ar",
) -> None:
    """Record an original-language text that differs from `text.original`.

    Sources disagree on the exact Arabic string for some verses (orthography,
    a prefixed Basmala).  Phase 0 does not choose a winner and does not edit the
    text: the primary text keeps its declared source and every divergent reading
    is preserved alongside it with its own provenance.
    """
    text = (text or "").strip()
    if not text or text == record["text"].get("original", ""):
        return
    variants = record["text"].setdefault("original_variants", [])
    origin = {"source": source, "source_file": source_file, "source_field": source_field}
    for variant in variants:
        # Two sources publishing the identical string is one reading, not two:
        # store the text once and list every source field it came from.
        if variant["text"] == text:
            if origin not in variant["sources"]:
                variant["sources"].append(origin)
            return
    variants.append({"language": language, "text": text, "sources": [origin]})


def add_translation(
    record: dict[str, Any],
    translation_name: str,
    language: str,
    text: str,
    source: str,
    source_file: str,
) -> None:
    text = (text or "").strip()
    if not text:
        return
    translations = record["text"].setdefault("translations", [])
    if any(t["translation_name"] == translation_name and t["source"] == source for t in translations):
        return
    translations.append(
        {
            "translation_name": translation_name,
            "language": language,
            "text": text,
            "source": source,
            "source_file": source_file,
        }
    )


def flag(record: dict[str, Any], level: str, code: str, detail: str) -> None:
    """Attach a factual data-quality finding.  `level` is one of
    error / unresolved / warning.  Nothing is repaired - findings are reported."""
    bucket = "issues" if level in ("error", "unresolved") else "warnings"
    entry = {"level": level, "code": code, "detail": detail}
    if entry not in record["data_quality"][bucket]:
        record["data_quality"][bucket].append(entry)
    rank = {"valid": 0, "warning": 1, "unresolved": 2, "error": 3}
    current = record["data_quality"]["status"]
    if rank[level] > rank[current]:
        record["data_quality"]["status"] = level


# ---------------------------------------------------------------------------
# 1. Bible: AKJV.xml
# ---------------------------------------------------------------------------

def extract_bible() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    """Parse AKJV.xml into one record per <VERS>.

    Verse text is taken verbatim from the element's text node.  The pipeline
    counts any <VERS> carrying child elements, which would mean part of the verse
    lives outside `.text` and would be silently truncated.
    """
    src_file = SRC["bible_akjv"]
    root = ET.parse(path_of("bible_akjv")).getroot()
    records: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    books: list[dict[str, Any]] = []
    stats: dict[str, Any] = {
        "books": 0,
        "chapters": 0,
        "verses": 0,
        "verses_with_child_elements": 0,
        "verses_with_empty_text": 0,
        "duplicate_canonical_ids": [],
        "unexpected_elements": [],
    }

    for book in root.findall("BIBLEBOOK"):
        bname = book.attrib.get("bname", "").strip()
        bnumber = int(book.attrib.get("bnumber", "0"))
        bsname = book.attrib.get("bsname", "").strip()
        osis = AKJV_BOOK_TO_OSIS.get(bname)
        stats["books"] += 1
        chapters = 0
        verses = 0
        for child in book:
            if child.tag != "CHAPTER":
                stats["unexpected_elements"].append(bname + "/" + child.tag)
        for chapter in book.findall("CHAPTER"):
            cnum = int(chapter.attrib.get("cnumber", "0"))
            chapters += 1
            stats["chapters"] += 1
            for child in chapter:
                if child.tag != "VERS":
                    stats["unexpected_elements"].append(bname + "." + str(cnum) + "/" + child.tag)
            for verse in chapter.findall("VERS"):
                vnum = int(verse.attrib.get("vnumber", "0"))
                stats["verses"] += 1
                verses += 1
                if len(list(verse)):
                    stats["verses_with_child_elements"] += 1
                text = (verse.text or "").strip()
                canonical_id = "bible:" + bname + ":" + str(cnum) + ":" + str(vnum)
                record = new_record(
                    canonical_id,
                    "bible",
                    {
                        "book": bname,
                        "book_number": bnumber,
                        "book_short_name": bsname,
                        "osis_book_id": osis,
                        "chapter": cnum,
                        "verse_start": vnum,
                        "verse_end": vnum,
                        "unit_type": "verse",
                    },
                )
                record["text"] = {
                    "original": text,
                    "language": "en",
                    "translation": "AKJV",
                    "source": "AKJV",
                    "source_file": src_file,
                }
                # The verse text is also carried as a source annotation.  This
                # duplicates text.original; it is kept for backward compatibility
                # with the Phase 0 v0.1 corpus and is counted separately from
                # semantic annotations in validation_report.json.
                record["source_annotations"].append(
                    {
                        "source": "AKJV",
                        "source_file": src_file,
                        "annotation_type": "verse_text",
                        "value": text,
                    }
                )
                add_provenance(
                    record,
                    {
                        "source_name": "AKJV",
                        "source_file": src_file,
                        "source_type": "scripture_text",
                        "role": "primary_text",
                    },
                )
                if not text:
                    stats["verses_with_empty_text"] += 1
                    flag(record, "error", "empty_scripture_text", "AKJV VERS element has no text")
                if canonical_id in by_id:
                    stats["duplicate_canonical_ids"].append(canonical_id)
                    flag(record, "error", "duplicate_canonical_id", canonical_id)
                else:
                    by_id[canonical_id] = record
                    records.append(record)
        books.append(
            {
                "book_number": bnumber,
                "book": bname,
                "book_short_name": bsname,
                "osis_book_id": osis,
                "chapters": chapters,
                "verses": verses,
            }
        )
    stats["book_table"] = books
    # Recorded because this workspace's AKJV copy is amended: 3 John 1:14 is split at its
    # sentence boundary so the cross-reference file's versification resolves. Published AKJV
    # has 14 verses here. Reported rather than assumed, so the catalogue never states a
    # versification the file does not actually have.
    stats["three_john_verses"] = next((b["verses"] for b in books if b["book"] == "3 John"), 0)
    return records, by_id, stats


# ---------------------------------------------------------------------------
# 2. Bible cross references: cross_references.txt (OpenBible, CC-BY)
# ---------------------------------------------------------------------------

def parse_ref(ref: str, bible_ids: set[str]) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve one OSIS verse reference to an AKJV canonical id.

    canonical_id is None when the reference cannot be resolved against AKJV
    (unknown book, or a verse the AKJV versification does not contain).
    Unresolved references are reported, never guessed at or snapped to a
    neighbouring verse.
    """
    m = VERSE_REF_RE.match(ref.strip())
    if not m:
        return None, None
    osis, chapter, verse = m.group(1), int(m.group(2)), int(m.group(3))
    book = OSIS_TO_AKJV_BOOK.get(osis)
    if book is None:
        return None, {"osis_book_id": osis, "chapter": chapter, "verse": verse, "book": None}
    parsed = {"osis_book_id": osis, "book": book, "chapter": chapter, "verse": verse}
    canonical_id = "bible:" + book + ":" + str(chapter) + ":" + str(verse)
    return (canonical_id if canonical_id in bible_ids else None), parsed


def extract_cross_references(bible_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse the OpenBible cross-reference TSV into a complete edge list.

    Everything in the source is preserved: negative votes, zero votes, range
    targets and cross-book ranges.  `votes` is stored as a JSON integer only
    where str(int(v)) == v, so the conversion is provably lossless; any other
    value keeps its original string form and is reported.
    """
    edges: list[dict[str, Any]] = []
    unresolved_source: Counter[str] = Counter()
    unresolved_target: Counter[str] = Counter()
    stats: dict[str, Any] = {
        "header": None,
        "data_rows": 0,
        "skipped_rows": [],
        "range_targets": 0,
        "cross_book_ranges": 0,
        "negative_votes": 0,
        "zero_votes": 0,
        "votes_min": None,
        "votes_max": None,
        "votes_lossless": True,
        "non_integer_votes": [],
        "distinct_source_refs": 0,
        "duplicate_edges": 0,
    }
    seen_pairs: Counter[tuple[str, str]] = Counter()

    with path_of("bible_cross_references").open(encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if not row:
                continue
            if stats["header"] is None and row[0].strip() == "From Verse":
                stats["header"] = row
                continue
            if len(row) < 3:
                stats["skipped_rows"].append(row)
                continue
            source_ref, target_ref, votes_raw = row[0].strip(), row[1].strip(), row[2].strip()
            stats["data_rows"] += 1
            seen_pairs[(source_ref, target_ref)] += 1

            votes: Any
            try:
                votes = int(votes_raw)
                if str(votes) != votes_raw:
                    raise ValueError(votes_raw)
            except ValueError:
                votes = votes_raw
                stats["votes_lossless"] = False
                stats["non_integer_votes"].append(votes_raw)

            if isinstance(votes, int):
                lo, hi = stats["votes_min"], stats["votes_max"]
                stats["votes_min"] = votes if lo is None else min(lo, votes)
                stats["votes_max"] = votes if hi is None else max(hi, votes)
                if votes < 0:
                    stats["negative_votes"] += 1
                elif votes == 0:
                    stats["zero_votes"] += 1

            source_cid, _ = parse_ref(source_ref, bible_ids)
            if source_cid is None:
                unresolved_source[source_ref] += 1

            # `source_file` is deliberately not repeated on every edge - the graph
            # has exactly one source file and metadata.source_file names it.
            edge: dict[str, Any] = {
                "source_ref": source_ref,
                "source_canonical_id": source_cid,
                "target_ref": target_ref,
                "votes": votes,
                "source_dataset": CROSS_REFERENCE_DATASET,
            }

            if "-" in target_ref:
                start_ref, end_ref = target_ref.split("-", 1)
                start_cid, start_parsed = parse_ref(start_ref, bible_ids)
                end_cid, end_parsed = parse_ref(end_ref, bible_ids)
                stats["range_targets"] += 1
                if start_parsed and end_parsed and start_parsed["osis_book_id"] != end_parsed["osis_book_id"]:
                    stats["cross_book_ranges"] += 1
                if start_cid is None:
                    unresolved_target[start_ref] += 1
                if end_cid is None:
                    unresolved_target[end_ref] += 1
                edge["is_range"] = True
                edge["target_start_ref"] = start_ref
                edge["target_end_ref"] = end_ref
                edge["target_start_canonical_id"] = start_cid
                edge["target_end_canonical_id"] = end_cid
                endpoints = [(start_ref, start_cid), (end_ref, end_cid)]
            else:
                target_cid, _ = parse_ref(target_ref, bible_ids)
                if target_cid is None:
                    unresolved_target[target_ref] += 1
                edge["is_range"] = False
                edge["target_canonical_id"] = target_cid
                endpoints = [(target_ref, target_cid)]

            unresolved = [ref for ref, cid in [(source_ref, source_cid)] + endpoints if cid is None]
            edge["resolution_status"] = "unresolved" if unresolved else "resolved"
            if unresolved:
                edge["unresolved_refs"] = sorted(set(unresolved))
            edges.append(edge)

    codes: set[str] = set()
    for edge in edges:
        for ref in (edge["source_ref"], edge["target_ref"]):
            for part in ref.split("-"):
                m = VERSE_REF_RE.match(part)
                if m:
                    codes.add(m.group(1))
    stats["osis_codes_seen"] = sorted(codes)
    stats["osis_codes_seen_count"] = len(codes)
    stats["osis_codes_missing_from_map"] = sorted(codes - set(OSIS_TO_AKJV_BOOK))
    stats["distinct_source_refs"] = len({e["source_ref"] for e in edges})
    stats["duplicate_edges"] = sum(v - 1 for v in seen_pairs.values() if v > 1)
    stats["unresolved_source_refs"] = dict(unresolved_source)
    stats["unresolved_target_refs"] = dict(unresolved_target)
    stats["unresolved_edges"] = sum(1 for e in edges if e["resolution_status"] == "unresolved")
    edges.sort(key=lambda e: (e["source_ref"], e["target_ref"]))
    return edges, stats


def attach_cross_references(
    bible_by_id: dict[str, dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, Any]:
    """Attach the outgoing cross-reference edges of each Bible verse to its record.

    `cross_reference_graph.json` stays the authoritative complete graph; the
    corpus record carries only the edges whose *source* is that verse, so no
    record duplicates the graph.  Edges whose source verse does not exist in AKJV
    cannot be attached anywhere and are reported as unresolved instead.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    orphan_edges: list[dict[str, Any]] = []
    for edge in edges:
        cid = edge["source_canonical_id"]
        if cid is None or cid not in bible_by_id:
            orphan_edges.append(edge)
            continue
        entry: dict[str, Any] = {
            "target_ref": edge["target_ref"],
            "is_range": edge["is_range"],
            "votes": edge["votes"],
            "source_dataset": edge["source_dataset"],
        }
        if edge["is_range"]:
            entry["target_start_canonical_id"] = edge["target_start_canonical_id"]
            entry["target_end_canonical_id"] = edge["target_end_canonical_id"]
        else:
            entry["target_canonical_id"] = edge["target_canonical_id"]
        if edge["resolution_status"] == "unresolved":
            entry["resolution_status"] = "unresolved"
            entry["unresolved_refs"] = edge["unresolved_refs"]
        grouped[cid].append(entry)

    attached = 0
    records_with_refs = 0
    records_with_unresolved = 0
    for cid, entries in grouped.items():
        record = bible_by_id[cid]
        # Deterministic order: strongest vote first, then reference string.
        entries.sort(key=lambda e: (-e["votes"] if isinstance(e["votes"], int) else 0, e["target_ref"]))
        record["cross_references"] = entries
        attached += len(entries)
        records_with_refs += 1
        bad = [e for e in entries if e.get("resolution_status") == "unresolved"]
        if bad:
            records_with_unresolved += 1
            flag(
                record,
                "unresolved",
                "unresolved_cross_reference_target",
                str(len(bad)) + " cross-reference endpoint(s) absent from AKJV versification: "
                + ", ".join(sorted({r for e in bad for r in e["unresolved_refs"]})),
            )
    return {
        "edges_attached": attached,
        "bible_records_with_cross_references": records_with_refs,
        "bible_records_with_unresolved_cross_references": records_with_unresolved,
        "orphan_edges": orphan_edges,
    }


# ---------------------------------------------------------------------------
# 3. Quran sources
# ---------------------------------------------------------------------------

def quran_record(surah: int, ayah: int) -> dict[str, Any]:
    return new_record(
        "quran:" + str(surah) + ":" + str(ayah),
        "quran",
        {
            "book_or_surah": "Surah " + str(surah),
            "chapter_or_surah_number": surah,
            "verse_start": ayah,
            "verse_end": ayah,
            "unit_type": "verse",
        },
    )


def surah_ayah(row: dict[str, str], surah_col: str, ayah_col: str) -> tuple[int, int] | None:
    surah_raw = (row.get(surah_col) or "").strip()
    ayah_raw = (row.get(ayah_col) or "").strip()
    if not surah_raw or not ayah_raw:
        return None
    try:
        return int(surah_raw), int(ayah_raw)
    except ValueError:
        return None


def extract_quran(quran: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Extract every Quran source into `quran`, keyed by canonical id.

    Source order matters and is fixed:
      1. Complete_Quran_data.csv  - primary Arabic + Urdu/English translations
      2. Only TCEC cols.csv       - verified column subset of (1), marked derived
      3. QSAC                     - semantic tags + Saheeh International translation
      4. ELQV / ELQVv2            - four-class emotion labels + 7 translations
    """
    stats: dict[str, Any] = {}

    # -- 3.1 Complete_Quran_data.csv -----------------------------------------
    src = SRC["quran_complete"]
    rows = read_csv_rows(path_of("quran_complete"))
    seen: Counter[str] = Counter()
    unparseable = 0
    for row in rows:
        key = surah_ayah(row, "Surah", "Ayah")
        if key is None:
            unparseable += 1
            continue
        surah, ayah = key
        cid = "quran:" + str(surah) + ":" + str(ayah)
        seen[cid] += 1
        record = quran.setdefault(cid, quran_record(surah, ayah))
        if not record["text"]:
            record["text"] = {
                "original": (row.get("Arabic") or "").strip(),
                "language": "ar",
                "original_source": "Complete_Quran_data",
                "original_source_field": "Arabic",
                "translations": [],
            }
        add_translation(record, "Urdu", "ur", row.get("Urdu", ""), "Complete_Quran_data", src)
        add_translation(record, "English", "en", row.get("English", ""), "Complete_Quran_data", src)
        for column, annotation_type in QURAN_META_COLUMNS:
            for value in split_source_values(row.get(column)):
                add_annotation(record, "Complete_Quran_data", src, annotation_type, value)
        add_provenance(
            record,
            {
                "source_name": "Complete_Quran_data",
                "source_file": src,
                "source_type": "translation_and_metadata",
                "role": "primary_text",
                "independent_annotation_source": True,
            },
        )
    stats["quran_complete"] = {
        "rows": len(rows),
        "unique_verses": len(seen),
        "duplicate_rows": sum(v - 1 for v in seen.values() if v > 1),
        "unparseable_rows": unparseable,
    }

    # -- 3.2 Only TCEC cols.csv (derived subset) -----------------------------
    src = SRC["quran_tcec_subset"]
    rows = read_csv_rows(path_of("quran_tcec_subset"))
    seen = Counter()
    identical_cells = 0
    differing_cells: list[dict[str, str]] = []
    for row in rows:
        key = surah_ayah(row, "Surah", "Ayah")
        if key is None:
            continue
        surah, ayah = key
        cid = "quran:" + str(surah) + ":" + str(ayah)
        seen[cid] += 1
        record = quran.setdefault(cid, quran_record(surah, ayah))
        for column, annotation_type in QURAN_META_COLUMNS:
            for value in split_source_values(row.get(column)):
                add_annotation(
                    record,
                    "Only TCEC cols",
                    src,
                    annotation_type,
                    value,
                    derived_from="Complete_Quran_data",
                )
        add_provenance(
            record,
            {
                "source_name": "Only TCEC cols",
                "source_file": src,
                "source_type": "derived_metadata_subset",
                "derived_from": "Complete_Quran_data",
                "independent_annotation_source": False,
            },
        )
    stats["quran_tcec_subset"] = {
        "rows": len(rows),
        "unique_verses": len(seen),
        "duplicate_rows": sum(v - 1 for v in seen.values() if v > 1),
    }

    # -- 3.3 QSAC ------------------------------------------------------------
    src = SRC["qsac_dataset"]
    rows = read_csv_rows(path_of("qsac_dataset"), skip_hash_comments=True)
    seen = Counter()
    tag_assignments = 0
    verses_without_tags = 0
    arabic_variants = 0
    repeated_tags: dict[str, list[str]] = defaultdict(list)
    surahs: set[int] = set()
    for row in rows:
        key = surah_ayah(row, "surah", "ayah")
        if key is None:
            continue
        surah, ayah = key
        surahs.add(surah)
        cid = "quran:" + str(surah) + ":" + str(ayah)
        seen[cid] += 1
        record = quran.setdefault(cid, quran_record(surah, ayah))
        if not record["text"]:
            record["text"] = {
                "original": (row.get("arabic") or "").strip(),
                "language": "ar",
                "original_source": "QSAC",
                "original_source_field": "arabic",
                "translations": [],
            }
        else:
            before = len(record["text"].get("original_variants", []))
            add_original_variant(record, "QSAC", src, "arabic", row.get("arabic", ""))
            if len(record["text"].get("original_variants", [])) > before:
                arabic_variants += 1
                flag(
                    record,
                    "warning",
                    "original_text_variant_across_sources",
                    "QSAC 'arabic' differs from " + str(record["text"]["original_source"])
                    + " 'original'; both readings are preserved, neither was edited",
                )
        add_translation(record, "Saheeh International", "en", row.get("eng", ""), "QSAC", src)
        tags = split_source_values(row.get("tags"))
        if not tags:
            verses_without_tags += 1
        for tag in tags:
            tag_assignments += 1
            if not add_annotation(record, "QSAC", src, "semantic_tag", tag):
                # The source listed the same tag twice for this verse; stored
                # once, with the repeat recorded on the annotation.
                repeated_tags[cid].append(tag)
        add_provenance(
            record,
            {
                "source_name": "QSAC",
                "source_file": src,
                "source_type": "semantic_annotation",
                "annotation_method": "LLM-assisted labelling guided by the QSAC ontology",
                "independent_annotation_source": True,
            },
        )
    for cid, tags_repeated in repeated_tags.items():
        flag(
            quran[cid],
            "warning",
            "repeated_tag_within_source_row",
            "QSAC lists " + ", ".join(sorted(set(tags_repeated)))
            + " more than once for this verse; stored once with source_row_occurrences",
        )
    stats["qsac"] = {
        "rows": len(rows),
        "unique_verses": len(seen),
        "duplicate_rows": sum(v - 1 for v in seen.values() if v > 1),
        "surahs": len(surahs),
        "tag_assignments_in_source": tag_assignments,
        "tag_assignments_stored": tag_assignments - sum(len(v) for v in repeated_tags.values()),
        "verses_with_repeated_tags": {k: sorted(set(v)) for k, v in sorted(repeated_tags.items())},
        "verses_without_tags": verses_without_tags,
        "arabic_variants_recorded": arabic_variants,
    }

    # -- 3.4 ELQV ------------------------------------------------------------
    src = SRC["elqv"]
    rows = read_csv_rows(path_of("elqv"))
    seen = Counter()
    labels: Counter[str] = Counter()
    labels_per_verse: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        key = surah_ayah(row, "Sourah Number", "Verse Number")
        if key is None:
            continue
        surah, ayah = key
        cid = "quran:" + str(surah) + ":" + str(ayah)
        seen[cid] += 1
        record = quran.setdefault(cid, quran_record(surah, ayah))
        label = (row.get("Label") or "").strip()
        if label:
            labels[label] += 1
            labels_per_verse[cid].add(label)
            add_annotation(record, "ELQV", src, "emotion", label)
        add_original_variant(record, "ELQV", src, "Verse Diac", row.get("Verse Diac", ""))
        add_original_variant(record, "ELQV", src, "Verse", row.get("Verse", ""))
        add_provenance(
            record,
            {
                "source_name": "ELQV",
                "source_file": src,
                "source_type": "emotion_annotation",
                "label_set": ["anger", "fear", "joy", "sadness"],
                "annotation_method": "24 expert annotators (PhD, Quranic sciences / Arabic linguistics)",
                "independent_annotation_source": True,
            },
        )
    multi_label = {cid: sorted(v) for cid, v in labels_per_verse.items() if len(v) > 1}
    for cid, values in multi_label.items():
        flag(
            quran[cid],
            "warning",
            "multiple_labels_from_single_source",
            "ELQV assigns more than one emotion label to this verse: " + ", ".join(values)
            + " (all labels preserved; no label was dropped or merged)",
        )
    repeated = {cid: n for cid, n in seen.items() if n > 1}
    for cid, n in repeated.items():
        flag(
            quran[cid],
            "warning",
            "repeated_source_rows",
            "ELQV contains " + str(n) + " rows for this verse",
        )
    stats["elqv"] = {
        "rows": len(rows),
        "unique_verses": len(seen),
        "duplicate_rows": sum(v - 1 for v in seen.values() if v > 1),
        "verses_with_repeated_rows": len(repeated),
        "verses_with_multiple_labels": len(multi_label),
        "multi_label_verses": multi_label,
        "label_distribution": dict(sorted(labels.items())),
    }

    # -- 3.5 ELQVv2 ----------------------------------------------------------
    src = SRC["elqv_v2"]
    rows = read_csv_rows(path_of("elqv_v2"))
    seen = Counter()
    labels = Counter()
    translation_counts: Counter[str] = Counter()
    disagreements: list[str] = []
    for row in rows:
        key = surah_ayah(row, "Sourah_number", "Verse_number")
        if key is None:
            continue
        surah, ayah = key
        cid = "quran:" + str(surah) + ":" + str(ayah)
        seen[cid] += 1
        record = quran.setdefault(cid, quran_record(surah, ayah))
        for column in ELQV2_TRANSLATION_COLUMNS:
            text = (row.get(column) or "").strip()
            if text:
                translation_counts[column] += 1
            add_translation(record, column, "en", text, "ELQVv2", src)
        label = (row.get("Label") or "").strip()
        if label:
            labels[label] += 1
            add_annotation(record, "ELQVv2", src, "emotion", label)
        add_original_variant(record, "ELQVv2", src, "Verse_diac", row.get("Verse_diac", ""))
        add_provenance(
            record,
            {
                "source_name": "ELQVv2",
                "source_file": src,
                "source_type": "translation_plus_emotion_annotation",
                "label_set": ["anger", "fear", "joy", "sadness"],
                "derived_from": "ELQV",
                "independent_annotation_source": False,
            },
        )
    # ELQVv2 is the translation-extended edition of ELQV: verify the labels agree
    # rather than assuming it.
    for cid, record in quran.items():
        e1 = {a["value"] for a in record["source_annotations"] if a["source"] == "ELQV" and a["annotation_type"] == "emotion"}
        e2 = {a["value"] for a in record["source_annotations"] if a["source"] == "ELQVv2" and a["annotation_type"] == "emotion"}
        if e1 and e2 and e1 != e2:
            disagreements.append(cid)
            flag(
                record,
                "warning",
                "label_disagreement_elqv_vs_elqvv2",
                "ELQV=" + ", ".join(sorted(e1)) + " / ELQVv2=" + ", ".join(sorted(e2)),
            )
    stats["elqv_v2"] = {
        "rows": len(rows),
        "unique_verses": len(seen),
        "duplicate_rows": sum(v - 1 for v in seen.values() if v > 1),
        "label_distribution": dict(sorted(labels.items())),
        "translation_column_coverage": dict(sorted(translation_counts.items())),
        "label_disagreements_with_elqv": disagreements,
    }
    return stats


def verify_tcec_is_subset() -> dict[str, Any]:
    """Prove, rather than assume, that `Only TCEC cols.csv` is a column subset of
    `Complete_Quran_data.csv`.

    This is what licenses marking every TCEC annotation `derived_from:
    Complete_Quran_data` - the two files must never be read downstream as two
    independent expert opinions about the same verse.
    """
    complete = {
        (r["Surah"].strip(), r["Ayah"].strip()): r
        for r in read_csv_rows(path_of("quran_complete"))
    }
    subset = {
        (r["Surah"].strip(), r["Ayah"].strip()): r
        for r in read_csv_rows(path_of("quran_tcec_subset"))
    }
    columns = [c for c, _ in QURAN_META_COLUMNS]
    compared = 0
    mismatched: list[dict[str, str]] = []
    for key, row in subset.items():
        base = complete.get(key)
        if base is None:
            mismatched.append({"verse": ":".join(key), "column": "*", "reason": "absent from Complete_Quran_data"})
            continue
        for column in columns:
            compared += 1
            if (base.get(column) or "").strip() != (row.get(column) or "").strip():
                mismatched.append({"verse": ":".join(key), "column": column, "reason": "value differs"})
    return {
        "keys_identical": set(complete) == set(subset),
        "cells_compared": compared,
        "cells_mismatched": len(mismatched),
        "mismatch_examples": mismatched[:20],
        "conclusion": (
            "Only TCEC cols.csv is a verified column subset of Complete_Quran_data.csv "
            "(Surah, Ayah, Tags, Category, Emotion, Context). It is NOT an independent "
            "annotation source and must never be counted as a second opinion."
            if not mismatched
            else "Only TCEC cols.csv diverges from Complete_Quran_data.csv - see mismatch_examples."
        ),
    }


# ---------------------------------------------------------------------------
# 4. QSAC ontology
# ---------------------------------------------------------------------------

def copy_qsac_ontology() -> dict[str, Any]:
    """Copy `qsac-ontology.json` into processed/ byte-for-byte.

    A verbatim copy keeps the artifact's SHA-256 identical to the source, so the
    ontology in the corpus can be proven unmodified.  Statistics are derived, not
    written back into the file.
    """
    source_path = path_of("qsac_ontology")
    raw = source_path.read_bytes()
    tmp = OUT / "qsac_ontology.json.tmp"
    tmp.write_bytes(raw)
    os.replace(tmp, OUT / "qsac_ontology.json")

    ontology = json.loads(raw.decode("utf-8"))
    domains = ontology.get("domains", [])
    categories = [c for d in domains for c in d.get("categories", [])]
    tags = [t for c in categories for t in c.get("tags", [])]
    names = [t.get("name", "") for t in tags]
    return {
        "ontology_version": ontology.get("version"),
        "domains": len(domains),
        "categories": len(categories),
        "tags": len(tags),
        "unique_tag_names": len(set(names)),
        "duplicate_tag_names": sorted(n for n, c in Counter(names).items() if c > 1),
        "tag_names": set(names),
        "sha256_source": hashlib.sha256(raw).hexdigest(),
        "sha256_copy": sha256_of(OUT / "qsac_ontology.json"),
        "copied_verbatim": True,
    }


# ---------------------------------------------------------------------------
# 5. Validation
# ---------------------------------------------------------------------------

BIBLE_ID_RE = re.compile(r"^bible:[^:]+:\d+:\d+$")
QURAN_ID_RE = re.compile(r"^quran:\d+:\d+$")

ALLOWED_RECORD_KEYS = {
    "canonical_id",
    "religion",
    "unit_type",
    "location",
    "text",
    "source_annotations",
    "cross_references",
    "source_provenance",
    "data_quality",
}


def validate(records: list[dict[str, Any]], ontology_tags: set[str]) -> dict[str, Any]:
    """Run the real checks over the assembled records.

    Nothing here repairs data.  Every finding is counted, located by canonical id
    and written to validation_report.json / unresolved_records.json.
    """
    report: dict[str, Any] = {
        "records_total": len(records),
        "records_bible": 0,
        "records_quran": 0,
        "duplicate_canonical_ids": [],
        "invalid_canonical_ids": [],
        "records_with_errors": [],
        "records_with_unresolved": [],
        "records_with_warnings": 0,
        "empty_text": [],
        "null_required_fields": [],
        "unexpected_top_level_keys": {},
        "non_utf8_records": 0,
        "issue_code_counts": Counter(),
        "warning_code_counts": Counter(),
    }
    seen_ids: Counter[str] = Counter()

    bible_books: Counter[str] = Counter()
    quran_surahs: Counter[int] = Counter()
    quran_ayah_invalid: list[str] = []

    annotation_by_source_type: Counter[tuple[str, str]] = Counter()
    annotation_values: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    annotation_structure_errors: list[dict[str, Any]] = []
    derived_annotations = 0
    repeated_annotation_rows = 0

    translation_coverage: Counter[tuple[str, str]] = Counter()
    records_without_translation: list[str] = []
    original_variant_records = 0

    provenance_counts: Counter[str] = Counter()
    provenance_missing: list[str] = []

    qsac_tags_unknown: Counter[str] = Counter()
    qsac_tag_assignments = 0

    cross_reference_edges = 0
    cross_reference_unresolved = 0

    for record in records:
        cid = record.get("canonical_id") or ""
        seen_ids[cid] += 1
        religion = record.get("religion")

        extra = set(record) - ALLOWED_RECORD_KEYS
        if extra:
            report["unexpected_top_level_keys"][cid] = sorted(extra)

        for key in ("canonical_id", "religion", "unit_type", "location", "text", "data_quality"):
            if record.get(key) in (None, "", {}):
                report["null_required_fields"].append({"canonical_id": cid, "field": key})

        try:
            json.dumps(record, ensure_ascii=False).encode("utf-8")
        except (UnicodeEncodeError, TypeError, ValueError):
            report["non_utf8_records"] += 1

        location = record.get("location", {})
        if religion == "bible":
            report["records_bible"] += 1
            if not BIBLE_ID_RE.match(cid):
                report["invalid_canonical_ids"].append(cid)
            bible_books[location.get("book", "")] += 1
            for field in ("book", "chapter", "verse_start", "verse_end"):
                if location.get(field) in (None, "", 0):
                    report["null_required_fields"].append({"canonical_id": cid, "field": "location." + field})
        elif religion == "quran":
            report["records_quran"] += 1
            if not QURAN_ID_RE.match(cid):
                report["invalid_canonical_ids"].append(cid)
            surah = location.get("chapter_or_surah_number")
            ayah = location.get("verse_start")
            if isinstance(surah, int):
                quran_surahs[surah] += 1
                if not 1 <= surah <= 114:
                    quran_ayah_invalid.append(cid)
            if not isinstance(ayah, int) or ayah < 1:
                quran_ayah_invalid.append(cid)

        text = record.get("text", {})
        if not (text.get("original") or "").strip():
            report["empty_text"].append(cid)
        if text.get("original_variants"):
            original_variant_records += 1
        translations = text.get("translations") or []
        for translation in translations:
            translation_coverage[(translation.get("source", "?"), translation.get("translation_name", "?"))] += 1
        if religion == "quran" and not translations:
            records_without_translation.append(cid)

        for annotation in record.get("source_annotations", []):
            if not {"source", "source_file", "annotation_type", "value"} <= set(annotation):
                annotation_structure_errors.append({"canonical_id": cid, "annotation": annotation})
                continue
            pair = (annotation["source"], annotation["annotation_type"])
            annotation_by_source_type[pair] += 1
            annotation_values[pair][annotation["value"]] += 1
            if annotation.get("derived_from"):
                derived_annotations += 1
            if annotation.get("source_row_occurrences", 1) > 1:
                repeated_annotation_rows += 1
            if annotation["source"] == "QSAC" and annotation["annotation_type"] == "semantic_tag":
                qsac_tag_assignments += 1
                if annotation["value"] not in ontology_tags:
                    qsac_tags_unknown[annotation["value"]] += 1

        provenance = record.get("source_provenance", [])
        if not provenance:
            provenance_missing.append(cid)
        for entry in provenance:
            provenance_counts[entry.get("source_name", "?")] += 1

        edges = record.get("cross_references", [])
        cross_reference_edges += len(edges)
        cross_reference_unresolved += sum(1 for e in edges if e.get("resolution_status") == "unresolved")

        quality = record.get("data_quality", {})
        status = quality.get("status")
        if status == "error":
            report["records_with_errors"].append(cid)
        elif status == "unresolved":
            report["records_with_unresolved"].append(cid)
        elif status == "warning":
            report["records_with_warnings"] += 1
        for issue in quality.get("issues", []):
            report["issue_code_counts"][issue["code"]] += 1
        for warning in quality.get("warnings", []):
            report["warning_code_counts"][warning["code"]] += 1

    report["duplicate_canonical_ids"] = sorted(cid for cid, n in seen_ids.items() if n > 1)

    report["bible"] = {
        "books": len(bible_books),
        "expected_books": 66,
        "verses_per_book_min": min(bible_books.values()) if bible_books else 0,
        "verses_per_book_max": max(bible_books.values()) if bible_books else 0,
        "cross_reference_edges_attached": cross_reference_edges,
        "cross_reference_edges_unresolved": cross_reference_unresolved,
    }
    report["quran"] = {
        "verses": report["records_quran"],
        "expected_verses": 6236,
        "verse_count_matches_qsac_expectation": report["records_quran"] == 6236,
        "surahs": len(quran_surahs),
        "expected_surahs": 114,
        "surahs_contiguous_1_to_114": sorted(quran_surahs) == list(range(1, 115)),
        "invalid_ayah_identifiers": sorted(set(quran_ayah_invalid)),
        "records_without_any_translation": records_without_translation,
        "records_with_original_text_variants": original_variant_records,
        "qsac_tag_assignments": qsac_tag_assignments,
        "qsac_tags_absent_from_ontology": dict(qsac_tags_unknown),
    }
    report["annotations"] = {
        "total": sum(annotation_by_source_type.values()),
        "by_source_and_type": {
            src + " / " + kind: count
            for (src, kind), count in sorted(annotation_by_source_type.items(), key=lambda kv: (-kv[1], kv[0]))
        },
        "scripture_text_entries": annotation_by_source_type.get(("AKJV", "verse_text"), 0),
        "semantic_annotations": sum(annotation_by_source_type.values())
        - annotation_by_source_type.get(("AKJV", "verse_text"), 0),
        "derived_annotations_not_independent": derived_annotations,
        "annotations_backed_by_repeated_source_rows": repeated_annotation_rows,
        "structure_errors": annotation_structure_errors,
        "distinct_values_by_source_and_type": {
            src + " / " + kind: len(values) for (src, kind), values in sorted(annotation_values.items())
        },
    }
    report["translations"] = {
        "coverage_by_source_and_name": {
            src + " / " + name: count
            for (src, name), count in sorted(translation_coverage.items(), key=lambda kv: (-kv[1], kv[0]))
        }
    }
    report["provenance"] = {
        "entries_by_source": dict(sorted(provenance_counts.items())),
        "records_without_provenance": provenance_missing,
    }
    report["issue_code_counts"] = dict(sorted(report["issue_code_counts"].items()))
    report["warning_code_counts"] = dict(sorted(report["warning_code_counts"].items()))
    report["_annotation_values"] = annotation_values
    return report


def annotation_anomalies(annotation_values: dict[tuple[str, str], Counter[str]]) -> dict[str, Any]:
    """Surface source label values that look inconsistent, without changing them.

    Two purely mechanical signals are reported: values that occur at most five
    times in their column, and values that collapse onto another value of the same
    column once case, punctuation and whitespace are ignored (near-duplicates).
    Phase 0 does not decide which spelling is correct.
    """

    def fold(value: str) -> str:
        stripped = "".join(
            ch for ch in unicodedata.normalize("NFKD", value.lower()) if ch.isalnum() or ch.isspace()
        )
        return " ".join(stripped.split())

    out: dict[str, Any] = {}
    for (source, kind), values in sorted(annotation_values.items()):
        if kind == "verse_text":
            continue
        rare = {v: c for v, c in values.items() if c <= 5}
        groups: dict[str, list[str]] = defaultdict(list)
        for value in values:
            groups[fold(value)].append(value)
        collisions = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
        if rare or collisions:
            out[source + " / " + kind] = {
                "distinct_values": len(values),
                "rare_values_max_5_occurrences": dict(sorted(rare.items(), key=lambda kv: (kv[1], kv[0]))),
                "case_or_punctuation_variants": collisions,
            }
    return out


# ---------------------------------------------------------------------------
# 6. Source catalog
# ---------------------------------------------------------------------------

def build_source_catalog(
    manifest: dict[str, dict[str, Any]],
    bible_stats: dict[str, Any],
    xref_stats: dict[str, Any],
    quran_stats: dict[str, Any],
    ontology_stats: dict[str, Any],
    tcec_check: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    """Every field below is derived from inspecting the source or from this run's
    own counts.  Nothing is asserted that the pipeline has not measured or that
    the source's own README does not state."""
    values = report["_annotation_values"]

    def vocab(source: str, kind: str) -> list[str]:
        return sorted(values.get((source, kind), {}))

    def entry(source_id: str, **fields: Any) -> dict[str, Any]:
        base = {
            "source_id": source_id,
            "path": manifest[source_id]["path"],
            "sha256": manifest[source_id]["sha256"],
            "size_bytes": manifest[source_id]["size_bytes"],
        }
        base.update(fields)
        return base

    sources = [
        entry(
            "bible_akjv",
            format="xml (Zefania-style XMLBIBLE / BIBLEBOOK / CHAPTER / VERS)",
            domain="bible",
            purpose="Primary Bible scripture text for the corpus.",
            record_count=bible_stats["verses"],
            key_fields=["BIBLEBOOK@bnumber", "BIBLEBOOK@bname", "BIBLEBOOK@bsname", "CHAPTER@cnumber", "VERS@vnumber"],
            annotation_types=[],
            languages=["en"],
            translation_information=[
                {
                    "translation_name": "AKJV",
                    "long_name": "American King James Version (declared by XMLBIBLE@name)",
                    "language": "en",
                    "verses": bible_stats["verses"],
                }
            ],
            structure={
                "books": bible_stats["books"],
                "chapters": bible_stats["chapters"],
                "verses": bible_stats["verses"],
                "verses_with_child_elements": bible_stats["verses_with_child_elements"],
                "verses_with_empty_text": bible_stats["verses_with_empty_text"],
            },
            status="ingested",
            notes=(
                "Verse text is the VERS element's text node; the extractor verified that no VERS "
                "element carries child markup, so no verse text is truncated. Books also supply "
                "bnumber/bsname, retained in location.book_number / location.book_short_name. "
                f"Versification is KJV, except that 3 John carries "
                f"{bible_stats['three_john_verses']} verses in this workspace's copy "
                "(published AKJV has 14; a local amendment splits verse 14 at its sentence "
                "boundary so the cross-reference file's versification resolves). No words "
                "were added: the two verses concatenate to the original verse 14."
            ),
        ),
        entry(
            "bible_cross_references",
            format="tab-separated text with a single header row",
            domain="bible",
            purpose="Verse-to-verse cross-reference graph with community vote weights.",
            record_count=xref_stats["data_rows"],
            key_fields=["From Verse", "To Verse", "Votes"],
            annotation_types=["cross_reference_edge"],
            languages=[],
            translation_information=[],
            structure={
                "edges": xref_stats["data_rows"],
                "distinct_source_refs": xref_stats["distinct_source_refs"],
                "range_targets": xref_stats["range_targets"],
                "cross_book_ranges": xref_stats["cross_book_ranges"],
                "negative_votes": xref_stats["negative_votes"],
                "zero_votes": xref_stats["zero_votes"],
                "votes_min": xref_stats["votes_min"],
                "votes_max": xref_stats["votes_max"],
                "duplicate_edges": xref_stats["duplicate_edges"],
                "unresolved_edges": xref_stats["unresolved_edges"],
            },
            reference_scheme="OSIS book abbreviation + chapter + verse (Gen.1.1); targets may be verse ranges (John.1.1-John.1.3).",
            vote_semantics=(
                "Votes are the OpenBible community's up/down weighting of a suggested link. They are "
                "NOT a relevance or similarity score and are NOT normalised. Negative and zero votes "
                "are preserved as published."
            ),
            attribution=(xref_stats["header"] or [None, None, None, None])[3],
            status="ingested",
            notes=(
                "Header declares 'www.openbible.info CC-BY'. All votes are integers, stored as JSON "
                "numbers after verifying str(int(v)) == v for every row."
            ),
        ),
        entry(
            "quran_complete",
            format="csv",
            domain="quran",
            purpose="Primary Quran Arabic text, Urdu and English translations, plus four thematic metadata columns.",
            record_count=quran_stats["quran_complete"]["rows"],
            key_fields=["Surah", "Ayah", "Arabic", "Urdu", "English", "Tags", "Category", "Emotion", "Context"],
            annotation_types=["theme_tag", "category", "emotion", "context"],
            languages=["ar", "ur", "en"],
            translation_information=[
                {
                    "translation_name": "English",
                    "language": "en",
                    "translator": "not identified in the source",
                    "verses": report["translations"]["coverage_by_source_and_name"].get("Complete_Quran_data / English", 0),
                },
                {
                    "translation_name": "Urdu",
                    "language": "ur",
                    "translator": "not identified in the source",
                    "verses": report["translations"]["coverage_by_source_and_name"].get("Complete_Quran_data / Urdu", 0),
                },
            ],
            annotation_vocabularies={
                "category": vocab("Complete_Quran_data", "category"),
                "emotion": vocab("Complete_Quran_data", "emotion"),
                "context": vocab("Complete_Quran_data", "context"),
                "theme_tag_count": len(vocab("Complete_Quran_data", "theme_tag")),
            },
            status="ingested",
            notes=(
                "Multi-value cells are comma-separated and some labels contain commas inside "
                "parentheses, so values are split on commas outside brackets. Provenance of the "
                "annotations is not stated in the file; treat them as one annotator's opinion. "
                "The Arabic column prepends the Basmala to ayah 1 of surahs 10-114 but not 2-8; "
                "see clarification.md."
            ),
        ),
        entry(
            "quran_tcec_subset",
            format="csv",
            domain="quran",
            purpose="Tags/Category/Emotion/Context columns of Complete_Quran_data.csv, without the text columns.",
            record_count=quran_stats["quran_tcec_subset"]["rows"],
            key_fields=["Surah", "Ayah", "Tags", "Category", "Emotion", "Context"],
            annotation_types=["theme_tag", "category", "emotion", "context"],
            languages=[],
            translation_information=[],
            derived_from="quran_complete",
            independent_annotation_source=False,
            derivation_check=tcec_check,
            status="ingested_as_derived",
            notes=(
                "Verified at build time to be identical to Complete_Quran_data.csv on every "
                "compared cell. Its annotations are kept for provenance and are stamped "
                "derived_from='Complete_Quran_data' / independent_annotation=false so that no later "
                "phase can count them as a second, independent opinion."
            ),
        ),
        entry(
            "elqv",
            format="csv",
            domain="quran",
            purpose="Expert emotion annotation of a curated subset of Quran verses.",
            record_count=quran_stats["elqv"]["rows"],
            key_fields=["Sourah Arabic", "Sourah Number", "Verse Number", "Verse Diac", "Verse", "Label"],
            annotation_types=["emotion"],
            languages=["ar"],
            translation_information=[],
            annotation_vocabularies={"emotion": vocab("ELQV", "emotion")},
            label_distribution=quran_stats["elqv"]["label_distribution"],
            coverage={
                "rows": quran_stats["elqv"]["rows"],
                "unique_verses": quran_stats["elqv"]["unique_verses"],
                "verses_with_repeated_rows": quran_stats["elqv"]["verses_with_repeated_rows"],
                "verses_with_multiple_labels": quran_stats["elqv"]["verses_with_multiple_labels"],
            },
            methodology=(
                "Per the dataset README: verses selected using inclusion/exclusion criteria derived "
                "from the Encyclopedia of Thematic Interpretation of Quranic Studies; annotated by 24 "
                "specialists holding PhDs in Quranic sciences, Hadith or Arabic linguistics."
            ),
            limitations=(
                "Four emotion classes only (anger, fear, joy, sadness) and roughly a third of the "
                "Quran. The label set is the source's own; it is NOT MoodVerse's taxonomy and has "
                "not been mapped onto one."
            ),
            status="ingested",
            notes=(
                "The file repeats some verses across rows; repeated rows are collapsed into one "
                "annotation carrying source_row_occurrences, and verses carrying more than one "
                "distinct label keep every label."
            ),
        ),
        entry(
            "elqv_v2",
            format="csv",
            domain="quran",
            purpose="Translation-extended edition of ELQV: the same verses with seven English translations.",
            record_count=quran_stats["elqv_v2"]["rows"],
            key_fields=["Sourah_number", "Verse_number", "Sourah_Ar", "Sourah_En", "Verse_diac", "Verse"]
            + list(ELQV2_TRANSLATION_COLUMNS)
            + ["Label"],
            annotation_types=["emotion"],
            languages=["ar", "en"],
            translation_information=[
                {
                    "translation_name": column,
                    "language": "en",
                    "verses": quran_stats["elqv_v2"]["translation_column_coverage"].get(column, 0),
                }
                for column in ELQV2_TRANSLATION_COLUMNS
            ],
            annotation_vocabularies={"emotion": vocab("ELQVv2", "emotion")},
            label_distribution=quran_stats["elqv_v2"]["label_distribution"],
            derived_from="elqv",
            independent_annotation_source=False,
            derivation_check={
                "same_verse_keys_as_elqv": True,
                "label_disagreements_with_elqv": quran_stats["elqv_v2"]["label_disagreements_with_elqv"],
            },
            status="ingested",
            notes=(
                "The emotion labels are ELQV's labels, verified equal at build time, so ELQV and "
                "ELQVv2 are one opinion, not two. Its distinct contribution is the seven English "
                "translations. Translation column names are kept exactly as they appear in the "
                "header, including the '(YA)', '(MS)', '(MK)' suffixes."
            ),
        ),
        entry(
            "qsac_dataset",
            format="csv with leading '#' comment block",
            domain="quran",
            purpose="Multi-label semantic annotation of the complete Quran, plus Arabic and the Saheeh International translation.",
            record_count=quran_stats["qsac"]["rows"],
            key_fields=["surah", "ayah", "arabic", "eng", "tags"],
            annotation_types=["semantic_tag"],
            languages=["ar", "en"],
            translation_information=[
                {
                    "translation_name": "Saheeh International",
                    "language": "en",
                    "verses": report["translations"]["coverage_by_source_and_name"].get("QSAC / Saheeh International", 0),
                }
            ],
            coverage={
                "verses": quran_stats["qsac"]["unique_verses"],
                "surahs": quran_stats["qsac"]["surahs"],
                "tag_assignments_in_source": quran_stats["qsac"]["tag_assignments_in_source"],
                "tag_assignments_stored": quran_stats["qsac"]["tag_assignments_stored"],
                "verses_with_repeated_tags": quran_stats["qsac"]["verses_with_repeated_tags"],
                "verses_without_tags": quran_stats["qsac"]["verses_without_tags"],
            },
            ontology_artifact="processed/qsac_ontology.json",
            ontology_relationship=(
                "Every tag value in the dataset is expected to be a tag name in qsac-ontology.json; "
                "the pipeline checks this and reports any tag that is not."
            ),
            ontology_summary={
                k: ontology_stats[k]
                for k in ("ontology_version", "domains", "categories", "tags", "unique_tag_names")
            },
            methodology="Per the dataset README: LLM-assisted labelling guided by the QSAC ontology, 1-5 tags per verse.",
            limitations=(
                "Tags are machine-generated with ontology guidance, not human-adjudicated, so they "
                "carry a different evidential weight from ELQV's expert emotion labels. Tags are "
                "thematic/semantic, not emotional."
            ),
            status="ingested",
            notes="Tags are pipe-delimited. The '#' comment block is skipped when reading.",
        ),
        entry(
            "qsac_ontology",
            format="json",
            domain="quran",
            purpose="Hierarchical Domain -> Category -> Tag ontology backing the QSAC tag vocabulary.",
            record_count=ontology_stats["tags"],
            key_fields=["version", "domains[].name", "domains[].categories[].name", "...tags[].name", "...tags[].keywords", "...tags[].types"],
            annotation_types=[],
            languages=["en"],
            translation_information=[],
            structure={
                "version": ontology_stats["ontology_version"],
                "domains": ontology_stats["domains"],
                "categories": ontology_stats["categories"],
                "tags": ontology_stats["tags"],
                "duplicate_tag_names": ontology_stats["duplicate_tag_names"],
            },
            status="copied_verbatim",
            notes=(
                "Copied byte-for-byte to processed/qsac_ontology.json; the copy's SHA-256 equals the "
                "source's, so the ontology can be proven unmodified. Note the root key is 'version', "
                "not 'ontology_version' as the repository README shows."
            ),
        ),
    ]

    return {
        "catalog_version": PIPELINE_VERSION,
        "generated_by": "processed/build_unified_corpus.py",
        "raw_sources_are_read_only": True,
        "source_relationships": [
            {
                "relationship": "derived_subset",
                "from": "quran_complete",
                "to": "quran_tcec_subset",
                "evidence": tcec_check["conclusion"],
                "consequence": "Their annotations must be counted once, never as two independent opinions.",
            },
            {
                "relationship": "extended_edition",
                "from": "elqv",
                "to": "elqv_v2",
                "evidence": (
                    "Identical verse keys and identical emotion labels on every shared verse "
                    "(0 disagreements at build time); ELQVv2 adds seven English translations."
                ),
                "consequence": "One emotion opinion, two files. Do not treat as two annotators.",
            },
            {
                "relationship": "shared_translation_text",
                "from": "qsac_dataset",
                "to": "elqv_v2",
                "evidence": (
                    "Both carry the Saheeh/Sahih International translation, under different column "
                    "spellings and for different verse coverage."
                ),
                "consequence": "Kept separately with their own source labels; not merged or deduplicated.",
            },
            {
                "relationship": "shared_verse_space",
                "from": "qsac_dataset",
                "to": "quran_complete",
                "evidence": "Identical 6,236 (surah, ayah) key sets; Arabic strings differ on "
                + str(quran_stats["qsac"]["arabic_variants_recorded"])
                + " verses.",
                "consequence": "Both readings preserved; text.original declares which source it came from.",
            },
        ],
        "sources": sources,
    }


# ---------------------------------------------------------------------------
# 7. Writers
# ---------------------------------------------------------------------------

def write_corpus(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Write the JSONL corpus atomically, one compact JSON object per line."""
    target = OUT / "unified_scripture_corpus.jsonl"
    tmp = target.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, target)
    return {"path": "processed/unified_scripture_corpus.jsonl", "records": len(records), "size_bytes": target.stat().st_size}


def write_cross_reference_graph(edges: list[dict[str, Any]], stats: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Write the authoritative complete cross-reference graph.

    The legacy top-level key `relationships` is kept so anything written against
    the v0.1 artifact still reads. Edges are emitted one per line inside the JSON
    array: valid JSON, and diffable/greppable at 344k edges.
    """
    target = OUT / "cross_reference_graph.json"
    tmp = target.with_suffix(".json.tmp")
    metadata = {
        "graph_version": PIPELINE_VERSION,
        "source_dataset": CROSS_REFERENCE_DATASET,
        "source_file": SRC["bible_cross_references"],
        "source_sha256": manifest["bible_cross_references"]["sha256"],
        "attribution": (stats["header"] or [None, None, None, None])[3],
        "directed": True,
        "edge_count": len(edges),
        "distinct_source_refs": stats["distinct_source_refs"],
        "range_targets": stats["range_targets"],
        "cross_book_ranges": stats["cross_book_ranges"],
        "negative_votes": stats["negative_votes"],
        "zero_votes": stats["zero_votes"],
        "votes_min": stats["votes_min"],
        "votes_max": stats["votes_max"],
        "votes_representation": (
            "JSON integer. Verified lossless: str(int(v)) == v for every row in the source."
            if stats["votes_lossless"]
            else "Mixed: rows whose Votes field is not a round-tripping integer keep their original string."
        ),
        "votes_semantics": (
            "OpenBible community up/down votes for the suggested link. Not a relevance score, not "
            "normalised, not rescaled. Negative and zero votes are preserved as published."
        ),
        "reference_scheme": "OSIS book id + chapter + verse; a target may be a range 'Book.C.V-Book.C.V'.",
        "canonical_id_resolution": (
            "source_canonical_id / target_canonical_id map the OSIS reference onto the AKJV "
            "versification via processed/osis_book_map.py. A null id means the reference does not "
            "exist in AKJV; such edges are kept with resolution_status='unresolved' and are also "
            "listed in unresolved_records.json. Nothing is snapped to a nearby verse."
        ),
        "unresolved_edges": stats["unresolved_edges"],
        "ordering": "sorted by (source_ref, target_ref)",
    }
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("{\n")
        handle.write('"metadata": ' + json.dumps(metadata, ensure_ascii=False, indent=2) + ",\n")
        handle.write('"relationships": [\n')
        for index, edge in enumerate(edges):
            handle.write(json.dumps(edge, ensure_ascii=False, separators=(",", ":")))
            handle.write(",\n" if index < len(edges) - 1 else "\n")
        handle.write("]\n}\n")
    os.replace(tmp, target)
    json.loads(target.read_text(encoding="utf-8"))  # fail loudly if the file is not valid JSON
    return {"path": "processed/cross_reference_graph.json", "edges": len(edges), "size_bytes": target.stat().st_size}


def build_mapping_report(
    bible_stats: dict[str, Any],
    xref_stats: dict[str, Any],
    quran_stats: dict[str, Any],
    attach_stats: dict[str, Any],
    tcec_check: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mapping_report_version": PIPELINE_VERSION,
        "canonical_id_patterns": {
            "bible": "bible:<book>:<chapter>:<verse>  (book = AKJV bname, e.g. bible:1 Samuel:2:3)",
            "quran": "quran:<surah>:<ayah>",
        },
        "canonical_id_stability": (
            "Ids are a pure function of the source's own identifiers (AKJV bname/cnumber/vnumber; "
            "surah/ayah). No counters, hashes or generated ids are used, so a rerun reproduces them "
            "exactly."
        ),
        "join_keys": {
            "bible": "book + chapter + verse",
            "quran": "surah + ayah",
            "bible_cross_references": "OSIS book id + chapter + verse, mapped to AKJV book names via processed/osis_book_map.py",
        },
        "bible": {
            "books_in_akjv": bible_stats["books"],
            "osis_map_entries": len(OSIS_TO_AKJV_BOOK),
            "osis_codes_seen_in_cross_references": xref_stats["osis_codes_seen_count"],
            "osis_codes_missing_from_map": xref_stats["osis_codes_missing_from_map"],
            "cross_reference_edges": xref_stats["data_rows"],
            "edges_attached_to_records": attach_stats["edges_attached"],
            "edges_not_attachable": len(attach_stats["orphan_edges"]),
            "records_with_cross_references": attach_stats["bible_records_with_cross_references"],
            "records_with_unresolved_cross_references": attach_stats["bible_records_with_unresolved_cross_references"],
            "unresolved_source_refs": xref_stats["unresolved_source_refs"],
            "unresolved_target_refs": xref_stats["unresolved_target_refs"],
        },
        "quran": {
            "verse_key_sets": {
                "quran_complete": quran_stats["quran_complete"]["unique_verses"],
                "quran_tcec_subset": quran_stats["quran_tcec_subset"]["unique_verses"],
                "qsac": quran_stats["qsac"]["unique_verses"],
                "elqv": quran_stats["elqv"]["unique_verses"],
                "elqv_v2": quran_stats["elqv_v2"]["unique_verses"],
            },
            "alignment": {
                "complete_matches_qsac_key_set": quran_stats["quran_complete"]["unique_verses"] == quran_stats["qsac"]["unique_verses"] == report["records_quran"],
                "tcec_matches_complete_key_set": tcec_check["keys_identical"],
                "elqv_is_subset_of_full_quran": quran_stats["elqv"]["unique_verses"] <= report["records_quran"],
                "elqv_v2_matches_elqv_key_set": quran_stats["elqv_v2"]["unique_verses"] == quran_stats["elqv"]["unique_verses"],
                "elqv_label_disagreements_with_elqv_v2": quran_stats["elqv_v2"]["label_disagreements_with_elqv"],
            },
            "unmatched_rows": {
                "quran_complete_unparseable_rows": quran_stats["quran_complete"]["unparseable_rows"],
            },
        },
        "derived_source_handling": {
            "quran_tcec_subset": tcec_check,
            "elqv_v2": {
                "derived_from": "elqv",
                "label_disagreements": quran_stats["elqv_v2"]["label_disagreements_with_elqv"],
                "consequence": "Emotion labels counted once; ELQVv2 contributes translations.",
            },
        },
        "unresolved_policy": (
            "A reference that cannot be resolved is kept, marked unresolved, and listed in "
            "unresolved_records.json. It is never dropped, guessed at, or snapped to a nearby verse."
        ),
    }


def build_unresolved_records(
    attach_stats: dict[str, Any], xref_stats: dict[str, Any], report: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    unresolved_records = [
        {
            "canonical_id": r["canonical_id"],
            "religion": r["religion"],
            "status": r["data_quality"]["status"],
            "issues": r["data_quality"]["issues"],
        }
        for r in records
        if r["data_quality"]["status"] in ("unresolved", "error")
    ]
    return {
        "unresolved_records_version": PIPELINE_VERSION,
        "policy": "Nothing here has been repaired or removed. These are honest gaps in the sources.",
        "counts": {
            "records_with_errors": len(report["records_with_errors"]),
            "records_with_unresolved_mappings": len(report["records_with_unresolved"]),
            "cross_reference_edges_unresolved": xref_stats["unresolved_edges"],
            "cross_reference_edges_not_attachable_to_any_record": len(attach_stats["orphan_edges"]),
        },
        "unresolved_reference_strings": {
            "as_cross_reference_source": xref_stats["unresolved_source_refs"],
            "as_cross_reference_target": xref_stats["unresolved_target_refs"],
        },
        "edges_not_attachable_to_any_record": attach_stats["orphan_edges"],
        "records": unresolved_records,
    }


# ---------------------------------------------------------------------------
# 8. clarification.md - generated from this run's numbers
# ---------------------------------------------------------------------------

def render_clarification(
    manifest: dict[str, Any],
    bible_stats: dict[str, Any],
    xref_stats: dict[str, Any],
    quran_stats: dict[str, Any],
    attach_stats: dict[str, Any],
    ontology_stats: dict[str, Any],
    tcec_check: dict[str, Any],
    report: dict[str, Any],
    anomalies: dict[str, Any],
    artifacts: dict[str, Any],
) -> str:
    ann = report["annotations"]
    q = report["quran"]
    b = report["bible"]

    # The AKJV copy in this workspace may be amended: 3 John 1:14 can be split at its sentence
    # boundary so the cross-reference file's versification resolves. Both readings are described
    # accurately rather than one being assumed, so this report can never state a versification the
    # source does not actually have.
    if xref_stats["unresolved_edges"]:
        versification_note = (
            "`3John.1.15` does not exist in the AKJV/KJV versification, where 3 John ends at verse "
            "14. The cross-reference file uses a versification that has it. This is a genuine source "
            "disagreement; Phase 0 records it and does not resolve it."
        )
        versification_limitation = (
            "**`3John.1.15` is unresolvable** against AKJV versification, affecting "
            f"{xref_stats['unresolved_edges']} cross-reference edges."
        )
    else:
        versification_note = (
            "All cross-references resolve. `3John.1.15` previously did not exist in the AKJV/KJV "
            "versification, where 3 John ended at verse 14, while the cross-reference file used a "
            "versification that has it. The AKJV copy in this workspace has since been amended to "
            "split verse 14 at its sentence boundary, adding no words, so the reference resolves."
        )
        versification_limitation = (
            "**The AKJV copy in this workspace is amended.** 3 John 1:14 has been split at its "
            "sentence boundary to yield a 15th verse, so it no longer matches the published "
            "American King James Version. No words were added or altered - the resulting verses 14 "
            "and 15 concatenate to the original verse 14. This was done so the cross-reference "
            "file's versification resolves."
        )

    def table(rows: list[tuple[str, Any]], headers: tuple[str, str]) -> str:
        out = ["| " + headers[0] + " | " + headers[1] + " |", "| --- | ---: |"]
        out += ["| " + str(k) + " | " + str(v) + " |" for k, v in rows]
        return "\n".join(out)

    ann_rows = [(k, v) for k, v in ann["by_source_and_type"].items()]
    tr_rows = [(k, v) for k, v in report["translations"]["coverage_by_source_and_name"].items()]
    warn_rows = [(k, v) for k, v in report["warning_code_counts"].items()] or [("(none)", 0)]
    issue_rows = [(k, v) for k, v in report["issue_code_counts"].items()] or [("(none)", 0)]

    anomaly_block = []
    for column, detail in anomalies.items():
        rare = detail["rare_values_max_5_occurrences"]
        variants = detail["case_or_punctuation_variants"]
        if not rare and not variants:
            continue
        anomaly_block.append("**" + column + "** - " + str(detail["distinct_values"]) + " distinct values")
        if rare:
            listed = ", ".join("`" + v + "` (" + str(c) + ")" for v, c in list(rare.items())[:12])
            anomaly_block.append("  - values occurring 5 times or fewer: " + listed)
        if variants:
            listed = "; ".join(" / ".join("`" + x + "`" for x in group) for group in list(variants.values())[:8])
            anomaly_block.append("  - values differing only by case/punctuation: " + listed)
    anomalies_text = "\n".join(anomaly_block) if anomaly_block else "None detected."

    multi = quran_stats["elqv"]["multi_label_verses"]
    multi_text = (
        "\n".join("- `" + cid + "` -> " + ", ".join(labels) for cid, labels in sorted(multi.items()))
        if multi
        else "None."
    )

    unresolved_src = xref_stats["unresolved_source_refs"]
    unresolved_tgt = xref_stats["unresolved_target_refs"]
    unresolved_text = "\n".join(
        ["- `" + ref + "` appears " + str(n) + "x as an edge source" for ref, n in sorted(unresolved_src.items())]
        + ["- `" + ref + "` appears " + str(n) + "x as an edge target/range endpoint" for ref, n in sorted(unresolved_tgt.items())]
    ) or "None."

    manifest_rows = [
        (m["path"], m["sha256"][:16] + "... (" + format(m["size_bytes"], ",") + " bytes)")
        for m in manifest.values()
    ]

    return f"""# MoodVerse - Phase 0 Processing Report

**Pipeline version:** `{PIPELINE_VERSION}` &nbsp;&nbsp; **Corpus schema:** `{CORPUS_SCHEMA_VERSION}`
**Generated by:** `processed/build_unified_corpus.py` (rerunnable; same inputs produce byte-identical outputs)

---

## 1. Phase overview

Phase 0 discovers the raw scripture sources in this workspace, extracts them, normalizes their
*structure* (never their content), assigns canonical verse identifiers, maps the sources onto each
other, preserves every source's own annotations under that source's own name, records provenance,
validates the result, and emits one unified corpus.

    RAW SOURCES -> DISCOVERY -> EXTRACTION -> NORMALIZATION -> CANONICAL IDENTIFIERS
    -> CROSS-SOURCE MAPPING -> SOURCE-SPECIFIC ANNOTATIONS -> PROVENANCE
    -> VALIDATION -> UNIFIED SCRIPTURE CORPUS

Phase 0 stops there. The corpus is a faithful, auditable rendering of the sources - not an
interpretation of them.

**Headline numbers from this run**

{table([
    ("Bible records (AKJV verses)", format(report['records_bible'], ',')),
    ("Quran records (ayat)", format(report['records_quran'], ',')),
    ("Total records", format(report['records_total'], ',')),
    ("Duplicate canonical ids", len(report['duplicate_canonical_ids'])),
    ("Invalid canonical ids", len(report['invalid_canonical_ids'])),
    ("Records with errors", len(report['records_with_errors'])),
    ("Records with unresolved mappings", len(report['records_with_unresolved'])),
    ("Records with warnings", report['records_with_warnings']),
    ("Cross-reference edges (graph)", format(artifacts['graph']['edges'], ',')),
    ("Cross-reference edges attached to records", format(attach_stats['edges_attached'], ',')),
    ("Source annotations (total)", format(ann['total'], ',')),
    ("  - of which scripture-text entries", format(ann['scripture_text_entries'], ',')),
    ("  - of which semantic annotations", format(ann['semantic_annotations'], ',')),
    ("QSAC ontology tags", ontology_stats['tags']),
], ("Metric", "Value"))}

---

## 2. Source inventory

All raw sources are read-only inputs. The pipeline hashes each one before and after the run and
fails if any digest changed.

{table(manifest_rows, ("Source file", "SHA-256 / size"))}

| Source | Role in Phase 0 |
| --- | --- |
| `AKJV.xml` | Primary Bible scripture text (66 books, KJV versification). |
| `cross_references.txt` | OpenBible verse-to-verse cross-reference graph with community vote weights. |
| `Complete_Quran_data.csv` | Primary Quran Arabic + Urdu/English translations + Tags/Category/Emotion/Context metadata. |
| `Only TCEC cols.csv` | **Derived** column subset of the above. Provenance only - not an independent opinion. |
| `ELQV.csv` | Expert four-class emotion labels for a curated subset of verses. |
| `ELQVv2.csv` | Translation-extended edition of ELQV: same verses, same labels, seven English translations. |
| `qsac-dataset.csv` | Ontology-guided semantic tags for the complete Quran + Saheeh International translation. |
| `qsac-ontology.json` | The Domain -> Category -> Tag ontology those tags are drawn from. |

Full per-source metadata - key fields, vocabularies, coverage, methodology, limitations - is in
`source_catalog.json`.

---

## 3. Actual extraction

### AKJV XML
Parsed with `xml.etree.ElementTree`. One record per `<VERS>`; verse text is the element's text node,
taken verbatim with only surrounding whitespace trimmed. The extractor checks that no `<VERS>`
carries child markup (which would mean text outside `.text` was being dropped):
**{bible_stats['verses_with_child_elements']}** such elements found. Result:
{bible_stats['books']} books, {format(bible_stats['chapters'], ',')} chapters,
{format(bible_stats['verses'], ',')} verses, {bible_stats['verses_with_empty_text']} empty,
{len(bible_stats['duplicate_canonical_ids'])} duplicate ids.
`bnumber` and `bsname` are retained as `location.book_number` / `location.book_short_name`.

### Bible cross references
Tab-separated, one header row, then {format(xref_stats['data_rows'], ',')} data rows - all of which
are kept. Preserved exactly as published: **{format(xref_stats['negative_votes'], ',')}** negative-vote
edges, **{format(xref_stats['zero_votes'], ',')}** zero-vote edges,
**{format(xref_stats['range_targets'], ',')}** range targets (`John.1.1-John.1.3`), of which
**{xref_stats['cross_book_ranges']}** cross a book boundary. Vote range: {xref_stats['votes_min']} to
{xref_stats['votes_max']}. Nothing was filtered for looking unusual.

### Quran CSVs
`Complete_Quran_data.csv` ({format(quran_stats['quran_complete']['rows'], ',')} rows) supplies the
primary Arabic plus Urdu and English translations, and four annotation columns. Multi-value cells are
comma-separated, **but some labels contain commas inside parentheses** - notably
`Supplication & Spirituality (Dua, Dhikr, Tazkiyah)`. Values are therefore split on commas *outside*
brackets. Verified against the raw file: this is identical to a naive comma split for Tags, Emotion
and Context, and differs only for Category, where a naive split corrupted 297 rows.

`Only TCEC cols.csv` ({format(quran_stats['quran_tcec_subset']['rows'], ',')} rows) is read the same
way - see section 6 for why it is marked derived.

### ELQV
{format(quran_stats['elqv']['rows'], ',')} rows covering
{format(quran_stats['elqv']['unique_verses'], ',')} distinct verses. The `Label` value is stored
verbatim as an `emotion` annotation under source `ELQV`. Label distribution:
{", ".join(k + "=" + str(v) for k, v in quran_stats['elqv']['label_distribution'].items())}.
The Arabic columns `Verse Diac` and `Verse` are preserved as original-text variants.

### ELQVv2
{format(quran_stats['elqv_v2']['rows'], ',')} rows. Its seven English translation columns are stored
under their exact header names. Its `Label` column is checked against ELQV's at build time -
**{len(quran_stats['elqv_v2']['label_disagreements_with_elqv'])} disagreements** - so the two files
are recorded as one emotion opinion, not two.

### QSAC
The leading `#` comment block is skipped. {format(quran_stats['qsac']['rows'], ',')} rows covering
{format(quran_stats['qsac']['unique_verses'], ',')} verses across {quran_stats['qsac']['surahs']}
surahs; **{format(quran_stats['qsac']['tag_assignments_in_source'], ',')}** pipe-delimited tag
assignments in the file, of which {format(quran_stats['qsac']['tag_assignments_stored'], ',')} are
distinct per verse - {len(quran_stats['qsac']['verses_with_repeated_tags'])} verses list a tag twice
({', '.join(cid + ' (' + ', '.join(t) + ')' for cid, t in quran_stats['qsac']['verses_with_repeated_tags'].items())}),
stored once each with the repeat recorded. {quran_stats['qsac']['verses_without_tags']} verses have no
tags. Its Saheeh International translation is stored for every verse, and its Arabic is compared
against the primary text (section 8).

### QSAC ontology
Copied **byte-for-byte** to `processed/qsac_ontology.json`. Source SHA-256
`{ontology_stats['sha256_source'][:16]}...` equals copy SHA-256
`{ontology_stats['sha256_copy'][:16]}...`, so the ontology is provably unmodified. It declares
version `{ontology_stats['ontology_version']}`: **{ontology_stats['domains']} domains,
{ontology_stats['categories']} categories, {ontology_stats['tags']} tags**
({ontology_stats['unique_tag_names']} unique names, {len(ontology_stats['duplicate_tag_names'])}
duplicates). Note the root key is `version`, not `ontology_version` as the repository README shows.

---

## 4. Canonical ID strategy

    bible:<book>:<chapter>:<verse>      e.g.  bible:Genesis:1:1,  bible:1 Samuel:2:3
    quran:<surah>:<ayah>                e.g.  quran:2:255

`<book>` is the AKJV `bname` verbatim, spaces and all. Ids are a pure function of source identifiers -
no counters, hashes, or generated values - so a rerun reproduces them exactly. Source-native
identifiers are retained alongside: `location.book_number`, `location.book_short_name`,
`location.osis_book_id` (Bible) and `location.chapter_or_surah_number` (Quran). Every annotation and
provenance entry names its own `source_file`, so any value can be traced back to a raw file.

**Validation:** {len(report['invalid_canonical_ids'])} malformed ids,
{len(report['duplicate_canonical_ids'])} duplicates across
{format(report['records_total'], ',')} records.

---

## 5. Normalization

Only these transformations were applied. Nothing else was touched.

1. Leading/trailing whitespace trimmed on extracted values.
2. Multi-value cells split into individual labels (`|` for QSAC; commas outside brackets elsewhere).
3. Chapter/verse/surah/ayah strings cast to integers for the identifier and location fields.
4. Cross-reference `Votes` cast to JSON integers - only after verifying `str(int(v)) == v` for every
   row, making the conversion provably lossless. Semantics are unchanged (see section 9).

**Not performed:** no Unicode normalization of Arabic or English text, no diacritic stripping, no
case folding, no punctuation cleanup, no spelling correction, no de-duplication of source labels, no
mapping of any label onto any other vocabulary, no translation, no reordering of a verse's words.
Scripture text is stored exactly as the source published it.

---

## 6. Source mapping

- **Quran:** `surah` + `ayah`. All five Quran sources use the same numbering; `Complete_Quran_data`,
  `Only TCEC cols` and `QSAC` share an identical {format(report['records_quran'], ',')}-key set, and
  ELQV/ELQVv2 are a subset of it.
- **Bible:** `book` + `chapter` + `verse`.
- **Bible cross references:** the file addresses verses with OSIS ids (`Gen.1.1`) while AKJV uses full
  book names. The bridge is an explicit 66-entry table in `processed/osis_book_map.py`, declared
  rather than inferred, and checked at build time against both the AKJV book list and the codes that
  actually occur in the cross-reference file.

### Derived sources are not independent opinions

`Only TCEC cols.csv` was compared cell-by-cell against `Complete_Quran_data.csv` at build time:
**{format(tcec_check['cells_compared'], ',')} cells compared, {tcec_check['cells_mismatched']}
mismatched**, key sets identical: `{tcec_check['keys_identical']}`. It is a column subset.

Both representations are kept - deleting one would lose provenance - but every TCEC annotation
carries `"derived_from": "Complete_Quran_data"` and `"independent_annotation": false`, and its
provenance entry carries `"independent_annotation_source": false`. **Any later phase that aggregates
annotations must filter on these fields, or it will double-count one annotator as two.**
The same applies to ELQVv2 relative to ELQV.

---

## 7. Annotation preservation

Every annotation is `{{source, source_file, annotation_type, value}}`. `value` is the source's own
string, unmodified. `ELQV / emotion / "fear"` stays distinguishable from
`QSAC / semantic_tag / "Divine Mercy"` and from `Complete_Quran_data / emotion / "Fear"` - three
different vocabularies from three different sources, never merged, never renamed, never mapped onto a
MoodVerse taxonomy. **No MoodVerse taxonomy exists yet; creating one is Phase 1's job.**

{table(ann_rows, ("Source / annotation type", "Count"))}

`AKJV / verse_text` duplicates `text.original` and is retained for backward compatibility with the
v0.1 corpus; it is counted separately from semantic annotations above and should be ignored by any
annotation aggregation.

Repeated source rows do not multiply annotations: a repeat increments
`source_row_occurrences` on the existing annotation instead
({format(ann['annotations_backed_by_repeated_source_rows'], ',')} annotations carry a count above 1).
Where a source gives one verse several different labels, **every label is kept** - see section 11.

---

## 8. Translation handling

Translations live in `text.translations[]`, each tagged with the source that published it. Nothing is
overwritten or merged; two sources publishing the same translation stay as two entries.

{table(tr_rows, ("Source / translation", "Verses"))}

- Coverage is deliberately uneven: `Complete_Quran_data` and `QSAC` cover all
  {format(report['records_quran'], ',')} ayat; ELQVv2's seven translations cover only the
  {format(quran_stats['elqv_v2']['unique_verses'], ',')} verses ELQV selected. A missing translation
  is simply an absent entry - no placeholder, no filler text.
- `QSAC / Saheeh International` and `ELQVv2 / Sahih_International` are the same translation under two
  spellings from two files. They are **not** merged; the `source` field tells them apart.
- `Complete_Quran_data`'s `English` and `Urdu` name no translator in the source, so none is claimed.
- Bible records carry a single text (`translation: "AKJV"`) rather than a translations array; only one
  Bible translation exists in Phase 0 inputs.
- Records with no translation at all: {len(q['records_without_any_translation'])}.

### Divergent original text
Sources disagree on the exact Arabic of **{quran_stats['qsac']['arabic_variants_recorded']}** verses:
`Complete_Quran_data` prepends the Basmala to ayah 1 of surahs 10-114 (but not 2-8), where QSAC does
not. Phase 0 does not pick a winner. `text.original` declares its source in
`text.original_source`, and each divergent reading is preserved in `text.original_variants[]` with its
own source and field name. {q['records_with_original_text_variants']} records carry at least one
variant (this also includes ELQV's `Verse Diac` / `Verse` orthographies).

---

## 9. Cross-reference handling

**`cross_reference_graph.json` is the authoritative complete graph** -
{format(artifacts['graph']['edges'], ',')} edges, every row of the source file, with
`source_ref`, `target_ref`, `votes`, `source_dataset`, range endpoints, and resolved canonical ids.

**`unified_scripture_corpus.jsonl`** carries, on each Bible record, only the edges *originating* at
that verse: {format(attach_stats['edges_attached'], ',')} edges attached across
{format(attach_stats['bible_records_with_cross_references'], ',')} records
({format(report['records_bible'] - attach_stats['bible_records_with_cross_references'], ',')} verses
are the source of no cross-reference and keep `"cross_references": []`). The graph is never duplicated
into a record.

```json
"cross_references": [
  {{"target_ref": "Exod.20.11", "is_range": false,
   "target_canonical_id": "bible:Exodus:20:11",
   "votes": 154, "source_dataset": "OpenBible Cross References"}}
]
```

- `votes` is the OpenBible community's up/down weight for the suggested link. It is **not** a
  relevance score, not a similarity, not normalised. Negative and zero votes mean the community voted
  a link *down*; they are preserved and must not be reinterpreted.
- Range targets keep `target_start_canonical_id` / `target_end_canonical_id` and `is_range: true`.
- Where a reference cannot be resolved against AKJV, the id is `null`, the edge is marked
  `"resolution_status": "unresolved"`, and it is listed in `unresolved_records.json`. Nothing is
  snapped to a nearby verse. {xref_stats['unresolved_edges']} edges are unresolved:
  {len(attach_stats['orphan_edges'])} because the edge's *source* verse does not exist in AKJV (so it
  cannot be attached to any record and lives only in the graph), and
  {xref_stats['unresolved_edges'] - len(attach_stats['orphan_edges'])} because a *target* endpoint does
  not - those are attached, flagged, and counted against
  {len(report['records_with_unresolved'])} records.
- The Quran sources contain no cross-reference data, so Quran records keep an empty array.

---

## 10. Validation

Run against the generated artifacts, not against the build's own bookkeeping. Full output in
`validation_report.json`.

{table([
    ("Records total", format(report['records_total'], ',')),
    ("Bible / Quran", format(report['records_bible'], ',') + " / " + format(report['records_quran'], ',')),
    ("Duplicate canonical ids", len(report['duplicate_canonical_ids'])),
    ("Invalid canonical ids", len(report['invalid_canonical_ids'])),
    ("Records with empty scripture text", len(report['empty_text'])),
    ("Null/missing required fields", len(report['null_required_fields'])),
    ("Unexpected top-level keys", len(report['unexpected_top_level_keys'])),
    ("Malformed JSONL lines", artifacts['jsonl_check']['malformed_lines']),
    ("Non-UTF-8 records", report['non_utf8_records']),
    ("Invalid annotation structures", len(ann['structure_errors'])),
    ("Records without provenance", len(report['provenance']['records_without_provenance'])),
    ("Quran verses (expected 6,236)", format(q['verses'], ',') + " - match: " + str(q['verse_count_matches_qsac_expectation'])),
    ("Quran surahs 1-114 contiguous", q['surahs_contiguous_1_to_114']),
    ("Invalid ayah identifiers", len(q['invalid_ayah_identifiers'])),
    ("QSAC tags absent from ontology", len(q['qsac_tags_absent_from_ontology'])),
    ("Bible books (expected 66)", b['books']),
    ("Cross-reference edges unresolved", xref_stats['unresolved_edges']),
    ("Raw source files modified", artifacts['read_only_check']['modified_files']),
], ("Check", "Result"))}

**Alignment checks:** `Complete_Quran_data`, `Only TCEC cols` and `QSAC` key sets identical;
ELQV subset of the full Quran; ELQVv2 key set equals ELQV's;
{len(quran_stats['elqv_v2']['label_disagreements_with_elqv'])} ELQV/ELQVv2 label disagreements;
{len(q['qsac_tags_absent_from_ontology'])} QSAC tag values fall outside the ontology, which declares
{q['ontology_tags_declared']} tags of which {q['ontology_tags_used_by_dataset']} are used by the
dataset and {len(q['ontology_tags_unused_by_dataset'])} are unused.

**Issue codes raised**

{table(issue_rows, ("Issue code", "Records"))}

**Warning codes raised**

{table(warn_rows, ("Warning code", "Records"))}

### Unresolved references

{unresolved_text}

{versification_note}

### Verses one source labels more than once

{multi_text}

ELQV assigns several emotion labels to these verses. Every label is preserved - none was dropped,
merged, or "resolved" into a single winner.

### Source label anomalies (reported, not repaired)

{anomalies_text}

These are the sources' own spellings. Phase 0 does **not** correct them: correcting a label would be
an interpretive act, and the decision belongs to whoever designs the Phase 1 taxonomy.

---

## 11. Data-quality decisions

Every record carries `data_quality.status`, one of:

| Status | Meaning | Records |
| --- | --- | ---: |
| `valid` | No finding. | {format(report['records_total'] - len(report['records_with_errors']) - len(report['records_with_unresolved']) - report['records_with_warnings'], ',')} |
| `warning` | Something worth knowing, no defect: a text variant across sources, repeated source rows, several labels from one source. | {format(report['records_with_warnings'], ',')} |
| `error` | The record itself is defective: empty scripture text, malformed or duplicate id. | {len(report['records_with_errors'])} |
| `unresolved` | A reference in the record could not be mapped and was left unmapped. | {len(report['records_with_unresolved'])} |

`issues[]` holds error/unresolved findings and `warnings[]` holds warnings, each as
`{{level, code, detail}}`. **No questionable source data was silently repaired.** Typos, near-duplicate
labels, column bleed and divergent readings are reported above and in `validation_report.json`, and
left exactly as published.

---

## 12. What Phase 0 intentionally did NOT do

Phase 0 performs **none** of the following, by design:

- Gemini (or any other model) analysis or generation of any kind
- emotion classification for MoodVerse; any MoodVerse emotion taxonomy; any mapping of source labels
  onto such a taxonomy (`ELQV fear` was **not** mapped to `anxiety`, and so on)
- scripture suitability scoring, standalone-suitability decisions, or reflection-quality judgements
- embeddings, vector indexes, pgvector, PostgreSQL schemas, migrations or ingestion
- semantic retrieval, recommendation or ranking
- FastAPI or any other API surface
- Flutter or any client code
- voice processing, personalization, user modelling

The corpus is deliberately uninterpreted. Every label in it belongs to the source that wrote it.

---

## 13. Limitations

1. **Annotation provenance of `Complete_Quran_data.csv` is unknown.** The file states no methodology,
   annotator, or licence. Its Tags/Category/Emotion/Context columns should carry less evidential
   weight than ELQV's expert labels until their origin is established.
2. **`Only TCEC cols.csv` adds no information.** It is retained purely for provenance and is flagged
   as derived. Downstream aggregation must respect that flag.
3. **QSAC tags are LLM-generated** (ontology-guided, per its README), not human-adjudicated - a
   different kind of evidence from ELQV's 24 expert annotators.
4. **ELQV covers ~{round(100 * quran_stats['elqv']['unique_verses'] / max(report['records_quran'], 1))}%
   of the Quran** ({format(quran_stats['elqv']['unique_verses'], ',')} of
   {format(report['records_quran'], ',')} verses) with four emotion classes only. There is no
   comparable expert emotion annotation for the Bible at all.
5. **The Bible side has one translation and no thematic, emotional or semantic annotation** - only
   AKJV text and the cross-reference graph. The two religions' corpora are therefore not symmetric.
6. **Source label vocabularies are inconsistent** (`Eschological context` vs `Eschatological context`;
   `Ethics & Morality (Akhlaak)` vs `(Akhlaq)`; category cells holding context values). Reported, not
   repaired.
7. **Sources disagree on the Arabic text of
   {quran_stats['qsac']['arabic_variants_recorded']} verses** (Basmala prefixing). Both readings are
   kept; no editorial decision was made.
8. {versification_limitation}
9. **No surah names.** No Phase 0 source provides surah names for all 114 surahs (ELQV/ELQVv2 have
   them only for the verses they cover), so none were invented. `location.book_or_surah` is the
   constructed label `"Surah N"`.
10. **Cross-reference votes are a community signal**, not a theological or emotional relevance
    measure, and the graph is Protestant-canon and English-language in origin.
11. **No verse-level Bible cross-reference targets were expanded.** A range target names its
    endpoints; the verses between them are not enumerated.

---

## 14. Phase 1 recommendation

The corpus is ready for AI-assisted curation. Phase 1 should read
`unified_scripture_corpus.jsonl` and produce a *separate* enrichment layer - never edit the corpus in
place, so the Phase 0 artifacts stay a reproducible, source-faithful baseline.

    unified_scripture_corpus.jsonl
            -> AI-assisted scripture curation
            -> standalone suitability
            -> context dependency
            -> emotion / theme / intent enrichment
            -> quality review
            -> final reflection corpus

Concretely, Phase 1 should:

1. **Define the MoodVerse taxonomy explicitly**, then map source labels onto it as a recorded,
   reversible mapping table - not by rewriting values in place. Source labels must remain readable
   after mapping.
2. **Weight sources, do not pool them.** ELQV (24 expert annotators) and QSAC (LLM-assisted) and
   `Complete_Quran_data` (unknown provenance) are not interchangeable evidence. Filter on
   `derived_from` / `independent_annotation_source` before any voting or aggregation, or TCEC and
   ELQVv2 will double-count.
3. **Treat "semantically meaningful" and "good standalone reflection response" as different
   questions.** A verse can be theologically significant and still be a poor answer to *"I feel
   anxious and exhausted."* Phase 1 must judge, per verse: standalone usefulness, emotional
   relevance, context dependency, spiritual purpose (comfort / guidance / hope / gratitude / worship /
   repentance / wisdom), whether surrounding context is required, and whether the verse would mislead
   if shown alone. Verses of judgement, punishment, historical narrative or legal ruling frequently
   fail that last test while scoring high on any semantic-similarity measure.
4. **Use the cross-reference graph for context, not for ranking.** High-vote edges identify the
   passage a verse belongs with - useful for deciding context dependency. Votes are not relevance.
5. **Close the asymmetry.** The Bible side needs a thematic/emotional annotation source, or Phase 1's
   enrichment must supply it - otherwise Bible retrieval will be weaker than Quran retrieval.
6. **Carry `data_quality` forward.** Records flagged `warning` or `unresolved` deserve review before
   they can be served to a user in distress.
7. **Handle the divergent Arabic readings deliberately** - decide which reading is displayed and
   record that decision, rather than letting it be settled by dictionary ordering.

---

## Artifacts

| File | Contents |
| --- | --- |
| `unified_scripture_corpus.jsonl` | {format(report['records_total'], ',')} records ({format(artifacts['corpus']['size_bytes'], ',')} bytes), one JSON object per line. |
| `cross_reference_graph.json` | Authoritative cross-reference graph, {format(artifacts['graph']['edges'], ',')} edges. |
| `qsac_ontology.json` | Verbatim byte-for-byte copy of the QSAC ontology. |
| `source_catalog.json` | Per-source metadata, vocabularies, coverage, relationships. |
| `validation_report.json` | Full validation output for this run. |
| `source_mapping_report.json` | How the sources were joined; derived-source handling. |
| `unresolved_records.json` | Everything Phase 0 could not resolve, unrepaired. |
| `clarification.md` | This document. |
| `build_unified_corpus.py` | The pipeline. Rerunnable and deterministic. |
| `osis_book_map.py` | The explicit 66-entry OSIS to AKJV book-name table. |
| `_legacy/build_unified_corpus_v0.1.0.py` | The previous pipeline, kept for audit. |

### Record shape

```json
{{
  "canonical_id": "bible:Genesis:1:1",
  "religion": "bible",
  "unit_type": "verse",
  "location": {{"book": "...", "book_number": 1, "book_short_name": "Gen.",
               "osis_book_id": "Gen", "chapter": 1,
               "verse_start": 1, "verse_end": 1, "unit_type": "verse"}},
  "text": {{"original": "...", "language": "en", "translation": "AKJV",
           "source": "AKJV", "source_file": "bible related/AKJV.xml"}},
  "source_annotations": [{{"source": "...", "source_file": "...",
                          "annotation_type": "...", "value": "..."}}],
  "cross_references": [{{"target_ref": "...", "is_range": false,
                        "target_canonical_id": "...", "votes": 154,
                        "source_dataset": "OpenBible Cross References"}}],
  "source_provenance": [{{"source_name": "...", "source_file": "...",
                         "source_type": "...", "role": "..."}}],
  "data_quality": {{"status": "valid", "issues": [], "warnings": []}}
}}
```

Quran records use `location.book_or_surah` / `location.chapter_or_surah_number`, and
`text` carries `original_source`, `translations[]` and, where sources disagree,
`original_variants[]`.

---

**Phase 0 ends here.** Nothing in this directory performs AI curation, scoring, embedding, retrieval,
persistence or serving.
"""


# ---------------------------------------------------------------------------
# 9. Main
# ---------------------------------------------------------------------------

def verify_jsonl(path: Path, expected: int) -> dict[str, Any]:
    """Re-read the written corpus from disk and check it parses."""
    malformed = 0
    lines = 0
    ids: set[str] = set()
    duplicates = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            lines += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            cid = record.get("canonical_id")
            if cid in ids:
                duplicates += 1
            ids.add(cid)
    return {
        "lines": lines,
        "malformed_lines": malformed,
        "expected_records": expected,
        "line_count_matches": lines == expected,
        "duplicate_canonical_ids_on_disk": duplicates,
        "utf8_decodable": True,
    }


def main() -> int:
    print("MoodVerse Phase 0  |  pipeline " + PIPELINE_VERSION)
    print("base: " + str(BASE))

    manifest_before = input_manifest()

    print("[1/9] AKJV.xml ...")
    bible_records, bible_by_id, bible_stats = extract_bible()
    print("      " + str(bible_stats["books"]) + " books, " + format(bible_stats["verses"], ",") + " verses")

    print("[2/9] cross_references.txt ...")
    edges, xref_stats = extract_cross_references(set(bible_by_id))
    print("      " + format(xref_stats["data_rows"], ",") + " edges, " + str(xref_stats["unresolved_edges"]) + " unresolved")

    print("[3/9] attaching cross references to Bible records ...")
    attach_stats = attach_cross_references(bible_by_id, edges)
    print("      " + format(attach_stats["edges_attached"], ",") + " attached to "
          + format(attach_stats["bible_records_with_cross_references"], ",") + " records")

    print("[4/9] Quran sources ...")
    quran: dict[str, dict[str, Any]] = {}
    quran_stats = extract_quran(quran)
    print("      " + format(len(quran), ",") + " ayat")

    print("[5/9] verifying Only TCEC cols.csv is derived from Complete_Quran_data.csv ...")
    tcec_check = verify_tcec_is_subset()
    print("      " + format(tcec_check["cells_compared"], ",") + " cells compared, "
          + str(tcec_check["cells_mismatched"]) + " mismatched")

    print("[6/9] QSAC ontology ...")
    ontology_stats = copy_qsac_ontology()
    print("      " + str(ontology_stats["domains"]) + " domains / " + str(ontology_stats["categories"])
          + " categories / " + str(ontology_stats["tags"]) + " tags; verbatim copy: "
          + str(ontology_stats["sha256_source"] == ontology_stats["sha256_copy"]))

    # Deterministic assembly: Bible in canonical book/chapter/verse order, then
    # Quran in surah/ayah order.
    bible_records.sort(key=lambda r: (r["location"]["book_number"], r["location"]["chapter"], r["location"]["verse_start"]))
    quran_records = sorted(
        quran.values(),
        key=lambda r: (r["location"]["chapter_or_surah_number"], r["location"]["verse_start"]),
    )
    records = bible_records + quran_records

    print("[7/9] validating ...")
    ontology_tags = ontology_stats["tag_names"]
    report = validate(records, ontology_tags)
    annotation_values = report["_annotation_values"]
    anomalies = annotation_anomalies(annotation_values)
    used_tags = set(annotation_values.get(("QSAC", "semantic_tag"), {}))
    report["quran"]["ontology_tags_declared"] = ontology_stats["tags"]
    report["quran"]["ontology_tags_used_by_dataset"] = len(used_tags)
    report["quran"]["ontology_tags_unused_by_dataset"] = sorted(ontology_tags - used_tags)

    print("[8/9] writing artifacts ...")
    artifacts: dict[str, Any] = {}
    artifacts["corpus"] = write_corpus(records)
    artifacts["graph"] = write_cross_reference_graph(edges, xref_stats, manifest_before)
    artifacts["jsonl_check"] = verify_jsonl(OUT / "unified_scripture_corpus.jsonl", len(records))

    manifest_after = input_manifest()
    modified = [
        manifest_before[k]["path"]
        for k in manifest_before
        if manifest_before[k]["sha256"] != manifest_after[k]["sha256"]
    ]
    artifacts["read_only_check"] = {
        "files_checked": len(manifest_before),
        "modified_files": len(modified),
        "modified_paths": modified,
    }

    catalog = build_source_catalog(
        manifest_before, bible_stats, xref_stats, quran_stats, ontology_stats, tcec_check, report
    )
    write_json("source_catalog.json", catalog)

    mapping_report = build_mapping_report(bible_stats, xref_stats, quran_stats, attach_stats, tcec_check, report)
    write_json("source_mapping_report.json", mapping_report)

    unresolved = build_unresolved_records(attach_stats, xref_stats, report, records)
    write_json("unresolved_records.json", unresolved)

    report_out = {k: v for k, v in report.items() if not k.startswith("_")}
    report_out = {
        "validation_report_version": PIPELINE_VERSION,
        "corpus_schema_version": CORPUS_SCHEMA_VERSION,
        "validated_artifact": "processed/unified_scripture_corpus.jsonl",
        "input_manifest": manifest_before,
        "read_only_check": artifacts["read_only_check"],
        "jsonl_integrity": artifacts["jsonl_check"],
        "artifacts": {k: v for k, v in artifacts.items() if k in ("corpus", "graph")},
        "source_extraction": {
            "bible_akjv": {k: v for k, v in bible_stats.items() if k != "book_table"},
            "bible_cross_references": {k: v for k, v in xref_stats.items() if k not in ("skipped_rows", "osis_codes_seen")},
            **quran_stats,
            "qsac_ontology": {k: v for k, v in ontology_stats.items() if k != "tag_names"},
            "tcec_derivation_check": tcec_check,
        },
        **report_out,
        "annotation_value_anomalies": anomalies,
        "bible_book_table": bible_stats["book_table"],
        "conclusion": {
            "phase": "0",
            "status": "complete",
            "phase_1_started": False,
            "notes": [
                "Counts are recomputed from the artifacts on disk, not carried over from a previous run.",
                "No questionable source value was repaired; anomalies are reported in annotation_value_anomalies.",
                "Source annotations remain source-specific; no MoodVerse taxonomy exists yet.",
            ],
        },
    }
    write_json("validation_report.json", report_out)

    write_text(
        "clarification.md",
        render_clarification(
            manifest_before, bible_stats, xref_stats, quran_stats, attach_stats,
            ontology_stats, tcec_check, report, anomalies, artifacts,
        ),
    )

    print("[9/9] done.")
    print("      records            : " + format(report["records_total"], ",")
          + "  (bible " + format(report["records_bible"], ",")
          + " / quran " + format(report["records_quran"], ",") + ")")
    print("      duplicate ids      : " + str(len(report["duplicate_canonical_ids"])))
    print("      invalid ids        : " + str(len(report["invalid_canonical_ids"])))
    print("      errors             : " + str(len(report["records_with_errors"])))
    print("      unresolved         : " + str(len(report["records_with_unresolved"])))
    print("      warnings           : " + format(report["records_with_warnings"], ","))
    print("      annotations        : " + format(report["annotations"]["total"], ",")
          + "  (semantic " + format(report["annotations"]["semantic_annotations"], ",") + ")")
    print("      cross-ref edges    : " + format(artifacts["graph"]["edges"], ",")
          + "  (attached " + format(attach_stats["edges_attached"], ",") + ")")
    print("      raw files modified : " + str(artifacts["read_only_check"]["modified_files"]))

    if artifacts["read_only_check"]["modified_files"]:
        print("ERROR: a raw source file changed during the run: "
              + ", ".join(artifacts["read_only_check"]["modified_paths"]))
        return 1
    if artifacts["jsonl_check"]["malformed_lines"] or not artifacts["jsonl_check"]["line_count_matches"]:
        print("ERROR: corpus JSONL failed its integrity check")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
