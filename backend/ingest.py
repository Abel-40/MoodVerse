"""Load the curated corpus into the database.

Reads the committed Phase 0 corpus and Phase 1 enrichment. Calls no AI provider
and costs nothing: the interpretation was done offline and is already in the
repository.

Idempotent. Re-running updates rows in place rather than duplicating them, so it
is safe to run after every re-curation.

Refuses any record whose enrichment digest disagrees with the corpus text. That
mismatch means enrichment was computed against a different text than the one
about to be served, which is exactly the drift the Phase 0 hashing exists to
catch.

    python ingest.py --dry-run          inspect without writing
    python ingest.py                     write
    python ingest.py --only-servable     skip records no query can return
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.session import SessionLocal
from app.models.scripture import (
    AddressedState,
    ContentAdvisory,
    IngestionRun,
    IntentScore,
    Scripture,
    ScriptureEnrichment,
    ScriptureTheme,
)
from app.services.embeddings import get_embedding_provider

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "data" / "processed" / "unified_scripture_corpus.jsonl"
ENRICHMENT = REPO / "data" / "processed" / "enrichment" / "curation" / "enrichment.jsonl"
DECISIONS = REPO / "data" / "processed" / "enrichment" / "curation" / "decisions.jsonl"

SERVABLE = ("INCLUDE", "INCLUDE_WITH_CONTEXT")


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(
            f"missing {path.relative_to(REPO)}. Build it first:\n"
            "  python pipeline/phase0/build_unified_corpus.py\n"
            "  python pipeline/phase1/build_enrichment.py --bootstrap"
        )
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def display_text(record: dict[str, Any]) -> tuple[str, str]:
    """The text served for this record. Mirrors mv_common.display_text."""
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


def location_of(record: dict[str, Any]) -> tuple[str, int, int]:
    loc = record.get("location", {})
    if record["religion"] == "bible":
        return loc.get("book", "?"), int(loc.get("chapter", 0)), int(loc.get("verse_start", 0))
    return (
        f"Surah {loc.get('chapter_or_surah_number', '?')}",
        int(loc.get("chapter_or_surah_number", 0)),
        int(loc.get("verse_start", 0)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-servable", action="store_true",
                        help="ingest only INCLUDE and INCLUDE_WITH_CONTEXT records")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    embedder = get_embedding_provider()
    corpus = {r["canonical_id"]: r for r in read_jsonl(CORPUS)}
    decisions = {d["canonical_id"]: d for d in read_jsonl(DECISIONS)}

    ingested = skipped = drifted = 0
    taxonomy_version = pipeline_version = None
    session = SessionLocal() if not args.dry_run else None

    try:
        for item in read_jsonl(ENRICHMENT):
            cid = item["canonical_id"]
            status = item["curation"]["status"]
            taxonomy_version = taxonomy_version or item.get("taxonomy_version")
            pipeline_version = pipeline_version or item.get("pipeline_version")

            if args.only_servable and status not in SERVABLE:
                skipped += 1
                continue

            record = corpus.get(cid)
            if record is None:
                skipped += 1
                continue

            text, text_source = display_text(record)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if item.get("corpus_text_sha256") and item["corpus_text_sha256"] != digest:
                # Enrichment was computed against different text than we would serve.
                drifted += 1
                continue

            if args.limit and ingested >= args.limit:
                break
            ingested += 1
            if args.dry_run:
                continue

            book, chapter, verse = location_of(record)
            session.execute(
                insert(Scripture)
                .values(
                    canonical_id=cid, religion=record["religion"], book_or_surah=book,
                    chapter=chapter, verse=verse, text=text,
                    text_source=text_source, text_sha256=digest,
                )
                .on_conflict_do_update(
                    index_elements=[Scripture.canonical_id],
                    set_={"text": text, "text_source": text_source, "text_sha256": digest},
                )
            )

            span = item.get("recommended_context_span") or {}
            decision = decisions.get(cid, {})
            values = dict(
                canonical_id=cid,
                taxonomy_version=item.get("taxonomy_version", "1.0.0"),
                curation_status=status,
                curation_confidence=item["curation"].get("curation_confidence"),
                rule_fired=decision.get("rule_fired"),
                expressed_primary=(item.get("expressed_affect") or {}).get("primary"),
                text_intensity=(item.get("expressed_affect") or {}).get("text_intensity"),
                standalone_usefulness=item.get("standalone_usefulness"),
                context_dependency=(item.get("context_dependency") or {}).get("level"),
                isolation_risk=(item.get("isolation_risk") or {}).get("level"),
                crisis_safe=(item.get("safety") or {}).get("crisis_safe"),
                context_span_start=span.get("start_canonical_id"),
                context_span_end=span.get("end_canonical_id"),
                embedding=embedder.embed(text),
                embedding_model=embedder.model_id,
            )
            session.execute(
                insert(ScriptureEnrichment)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[ScriptureEnrichment.canonical_id],
                    set_={k: v for k, v in values.items() if k != "canonical_id"},
                )
            )

            # Child rows are replaced wholesale: a re-curation may remove a
            # state or an advisory, and a merge would silently keep the old one.
            for model in (AddressedState, IntentScore, ScriptureTheme, ContentAdvisory):
                session.query(model).filter(model.canonical_id == cid).delete()

            for state in item.get("addressed_states") or []:
                session.add(AddressedState(
                    canonical_id=cid, state=state["state"],
                    emotional_relevance=state.get("emotional_relevance", 0),
                    evidence_span=state.get("evidence_span"),
                ))
            for intent, block in (item.get("purpose_suitability") or {}).items():
                session.add(IntentScore(
                    canonical_id=cid, intent=intent,
                    score=(block or {}).get("score", 0), basis=(block or {}).get("basis"),
                ))
            for theme in item.get("themes") or []:
                session.add(ScriptureTheme(canonical_id=cid, theme=theme))
            safety = item.get("safety") or {}
            for advisory in safety.get("content_advisories") or []:
                session.add(ContentAdvisory(canonical_id=cid, kind="advisory", value=advisory))
            for state in safety.get("avoid_for_states") or []:
                session.add(ContentAdvisory(canonical_id=cid, kind="avoid_state", value=state))

        if not args.dry_run:
            session.add(IngestionRun(
                taxonomy_version=taxonomy_version or "unknown",
                pipeline_version=pipeline_version,
                records_ingested=ingested, records_skipped=skipped,
                notes=f"drifted={drifted}",
            ))
            session.commit()
    finally:
        if session is not None:
            session.close()

    print(f"{'dry run: ' if args.dry_run else ''}ingested {ingested:,}")
    print(f"  skipped  {skipped:,}")
    print(f"  drifted  {drifted:,}  (enrichment digest did not match corpus text)")
    if drifted:
        print("  a drifted record means enrichment is stale; rebuild Phase 1 before serving.")
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
