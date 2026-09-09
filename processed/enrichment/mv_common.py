"""Shared helpers for the MoodVerse Phase 1 enrichment layer.

Standard library only, matching the Phase 0 convention. Everything here is
deterministic: same inputs produce byte-identical outputs.

The Phase 0 artefacts in ``processed/`` are treated as frozen. ``phase0_digests``
hashes them and ``assert_phase0_unchanged`` fails the build if any digest moved.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------

ENRICHMENT = Path(__file__).resolve().parent
PROCESSED = ENRICHMENT.parent
BASE = PROCESSED.parent

CORPUS = PROCESSED / "unified_scripture_corpus.jsonl"
XREF_GRAPH = PROCESSED / "cross_reference_graph.json"
QSAC_ONTOLOGY = PROCESSED / "qsac_ontology.json"
SOURCE_CATALOG = PROCESSED / "source_catalog.json"
VALIDATION_REPORT = PROCESSED / "validation_report.json"

TAXONOMY = ENRICHMENT / "taxonomy" / "taxonomy.json"

# Every Phase 0 artefact. Hashed before and after each run; any change is a
# hard failure. This is the Phase 0 read-only guard, extended to cover Phase 0's
# own outputs rather than only the raw sources.
PHASE0_FILES = (
    "unified_scripture_corpus.jsonl",
    "cross_reference_graph.json",
    "qsac_ontology.json",
    "source_catalog.json",
    "validation_report.json",
    "source_mapping_report.json",
    "unresolved_records.json",
    "clarification.md",
    "build_unified_corpus.py",
    "osis_book_map.py",
)

RAW_SOURCE_DIRS = ("bible related", "quran related")

# 3 John 1:14 is split in this workspace's AKJV copy, so the Bible carries 31,103
# verses rather than the published edition's 31,102. See processed/clarification.md.
EXPECTED_RECORDS = 37339
EXPECTED_BIBLE = 31103
EXPECTED_QURAN = 6236


# --------------------------------------------------------------------------
# encoding
# --------------------------------------------------------------------------

def setup_stdout() -> None:
    """Force UTF-8 on stdout/stderr.

    The corpus is UTF-8 but the default Windows console codepage here is cp1252,
    which raises UnicodeEncodeError the moment Arabic text is printed.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
            pass


# --------------------------------------------------------------------------
# hashing / immutability
# --------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def phase0_digests() -> dict[str, str]:
    """SHA-256 of every Phase 0 artefact, plus every raw source file."""
    digests: dict[str, str] = {}
    for name in PHASE0_FILES:
        path = PROCESSED / name
        if path.exists():
            digests[f"processed/{name}"] = sha256_file(path)
    for directory in RAW_SOURCE_DIRS:
        root = BASE / directory
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                digests[path.relative_to(BASE).as_posix()] = sha256_file(path)
    return digests


def assert_phase0_unchanged(before: dict[str, str], after: dict[str, str]) -> None:
    """Fail loudly if any frozen file changed during the run."""
    changed = sorted(k for k in before if before[k] != after.get(k))
    missing = sorted(k for k in before if k not in after)
    added = sorted(k for k in after if k not in before)
    if changed or missing or added:
        raise SystemExit(
            "PHASE 0 IMMUTABILITY VIOLATION\n"
            f"  modified: {changed}\n  missing: {missing}\n  added: {added}"
        )


# --------------------------------------------------------------------------
# deterministic IO (same conventions as processed/build_unified_corpus.py)
# --------------------------------------------------------------------------

def write_json(path: Path, data: Any, indent: int | None = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=indent, sort_keys=False)
        handle.write("\n")
    os.replace(tmp, path)
    return path


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, path)
    return path


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return path


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


# --------------------------------------------------------------------------
# corpus access
# --------------------------------------------------------------------------

def iter_corpus() -> Iterator[dict[str, Any]]:
    """Yield every Phase 0 record in file order. Read-only."""
    yield from read_jsonl(CORPUS)


def display_text(record: dict[str, Any]) -> tuple[str, str]:
    """The text an annotator should judge, and the label of where it came from.

    Bible records carry a single AKJV text. Quran records carry Arabic as
    ``text.original`` plus several English translations; annotation is done
    against English, preferring Saheeh International (QSAC, covers all 6236
    ayat) and falling back to Complete_Quran_data's unattributed English.

    This is a *deterministic display choice*, recorded on every enrichment
    record as ``display_text_ref``. It is not a claim that one reading is
    correct - decision 15 in PHASE1A_DESIGN.md remains open, and records whose
    Arabic diverges across sources are flagged regardless of which English is
    shown.
    """
    text = record.get("text", {})
    if record["religion"] == "bible":
        return text.get("original", ""), "AKJV"
    for preferred in ("Saheeh International", "English"):
        for translation in text.get("translations", []):
            if translation.get("translation_name") == preferred:
                return translation.get("text", ""), f"{translation.get('source')}/{preferred}"
    translations = text.get("translations", [])
    if translations:
        first = translations[0]
        return first.get("text", ""), f"{first.get('source')}/{first.get('translation_name')}"
    return text.get("original", ""), text.get("original_source", "unknown")


def independent_annotations(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Source annotations that count as evidence.

    Drops two things:
      * ``independent_annotation is False`` - Only TCEC cols and ELQVv2, which
        are verified duplicates. 35% of the corpus's stored annotations. Pooling
        them would count one annotator as two.
      * ``verse_text`` - the AKJV entry duplicating ``text.original``, retained
        by Phase 0 for v0.1 compatibility and explicitly not a semantic label.
    """
    out = []
    for annotation in record.get("source_annotations", []):
        if annotation.get("independent_annotation") is False:
            continue
        if annotation.get("annotation_type") == "verse_text":
            continue
        out.append(annotation)
    return out


# --------------------------------------------------------------------------
# taxonomy access
# --------------------------------------------------------------------------

class Taxonomy:
    """Loaded taxonomy with the value sets every other module validates against."""

    def __init__(self, path: Path = TAXONOMY) -> None:
        self.raw = read_json(path)
        self.version: str = self.raw["taxonomy_version"]
        axes = self.raw["axes"]
        self._axes = axes

        self.emotions = self._ids(axes["emotions"])
        self.themes = self._ids(axes["themes"])
        self.intents = self._ids(axes["intents"])
        self.situations = self._ids(axes["situations"])
        self.scripture_purposes = self._ids(axes["scripture_purposes"])

        self.intensity_levels = {v["id"] for v in axes["intensity"]["values"]}
        self.context_levels = {v["id"] for v in axes["context_dependency"]["values"]}
        self.dependency_reasons = {v["id"] for v in axes["context_dependency"]["dependency_reasons"]}

        subfields = axes["scripture_purposes"]["subfields"]
        self.speaker_roles = {v["id"] for v in subfields["speaker_role"]["values"]}
        self.promise_conditionality = {v["id"] for v in subfields["promise_conditionality"]["values"]}
        self.hard_exclusion_speakers = {
            v["id"] for v in subfields["speaker_role"]["values"] if v.get("hard_exclusion_trigger")
        }

        scales = axes["scales"]
        self.blockers = {v["id"] for v in scales["blockers"]}
        self.content_advisories = {v["id"] for v in scales["content_advisories"]}
        self.isolation_kinds = {v["id"] for v in scales["isolation_risk"]["kinds"]}
        self.confidence_bands = [b["value"] for b in scales["curation_confidence"]["bands"]]
        self.isolation_levels = {v["id"] for v in scales["isolation_risk"]["values"]}
        self.score_levels = {v["id"] for v in scales["standalone_usefulness"]["values"]}

        structural = axes["structural"]
        self.annotation_methods = [v["id"] for v in structural["annotation_methods"]["values"]]
        self.method_rank = {
            v["id"]: v["rank"] for v in structural["annotation_methods"]["values"]
        }
        self.curation_statuses = {v["id"] for v in structural["curation_status"]["values"]}
        self.revelation_periods = {v["id"] for v in structural["revelation_period"]["values"]}
        self.evidence_tiers = {
            v["id"]: v for v in structural["evidence_tiers"]["values"]
        }

        self.purpose_priors = {
            v["id"]: v.get("context_dependency_prior")
            for v in axes["scripture_purposes"]["values"]
        }

    @staticmethod
    def _ids(axis: dict[str, Any]) -> set[str]:
        return {v["id"] for v in axis["values"]}

    def tier_weight(self, tier: str) -> float:
        return float(self.evidence_tiers[tier]["weight"])

    def axis(self, name: str) -> dict[str, Any]:
        return self._axes[name]


# The source each annotation source belongs to, by evidence tier. Derived from
# the taxonomy so the two can never drift apart.
def source_tier_map(taxonomy: Taxonomy) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for tier_id, tier in taxonomy.evidence_tiers.items():
        for source in tier.get("sources", []):
            mapping[source] = tier_id
    return mapping
