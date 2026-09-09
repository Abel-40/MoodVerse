"""Agent annotation harness. Makes no network calls and costs nothing.

The development agent performs the interpretation that annotate.py would
otherwise buy from Gemini. Output lands in the same
``annotation/runs/<run_id>/responses.jsonl`` format, so build_enrichment.py
replays it unchanged and every downstream guarantee still holds: the annotator
still only proposes, and curation.py still decides the status.

The contract is identical to the Gemini one and is enforced by the *same*
validator, ``annotate.validate_response``. There is no second, weaker path: an
authored record that would have been rejected from Gemini is rejected here.

  worklist   emit the next N unannotated records with the exact text to judge
  ingest     validate an authored batch and merge it into the run, idempotently
  status     report how many records are annotated and how many remain

Resumable: ``worklist`` skips every canonical_id already recorded in any run.
Idempotent: re-ingesting a batch replaces those records in place rather than
appending a duplicate, so one record is never counted as two annotators.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import annotate
import mv_common as mv

RUNS_DIR = mv.ENRICHMENT / "annotation" / "runs"
PRIORS = mv.ENRICHMENT / "priors" / "deterministic_priors.jsonl"

# One run directory for the whole agent pass. All batches accumulate here.
#
# This matters: build_enrichment.reconcile() treats two responses for the same
# canonical_id as two independent annotators and promotes the record to
# `ai_reviewed`. Splitting a single annotator's batches across run directories
# would manufacture agreement that does not exist. One annotator, one run.
AGENT_RUN_ID = "agent-claude-opus-5"

ANNOTATOR = "claude-opus-5"
CONTEXT_WINDOW = 2


# ---------------------------------------------------------------------------
# corpus / state
# ---------------------------------------------------------------------------

def annotated_ids() -> set[str]:
    """Every canonical_id already annotated, across every run."""
    done: set[str] = set()
    if not RUNS_DIR.exists():
        return done
    for run_dir in sorted(p for p in RUNS_DIR.iterdir() if p.is_dir()):
        responses = run_dir / "responses.jsonl"
        if responses.exists():
            for row in mv.read_jsonl(responses):
                if row.get("canonical_id"):
                    done.add(row["canonical_id"])
    return done


def load_corpus() -> tuple[dict[str, dict], list[str]]:
    by_id = {r["canonical_id"]: r for r in mv.iter_corpus()}
    return by_id, list(by_id)


def reference_of(record: dict) -> str:
    """A human-readable location, for the worklist only.

    Never written into an annotation: free-text fields containing a scripture
    reference are rejected by the validator.
    """
    loc = record.get("location") or {}
    if record["religion"] == "bible":
        return f"{loc.get('book', '?')} {loc.get('chapter', '?')}:{loc.get('verse_start', '?')}"
    return (f"Surah {loc.get('chapter_or_surah_number', '?')}, "
            f"ayah {loc.get('verse_start', '?')}")


# ---------------------------------------------------------------------------
# worklist
# ---------------------------------------------------------------------------

def cmd_worklist(args: argparse.Namespace) -> int:
    taxonomy = mv.Taxonomy()
    done = annotated_ids()
    by_id, order = load_corpus()
    position_of = {cid: i for i, cid in enumerate(order)}
    priors = {row["canonical_id"]: row for row in mv.read_jsonl(PRIORS)}

    selected = annotate.select_records(None, args.religion, args.tier)
    pending = [r for r in selected if r["canonical_id"] not in done]
    batch = pending[args.offset: args.offset + args.limit]

    items = []
    for record in batch:
        cid = record["canonical_id"]
        verse_text, text_ref = mv.display_text(record)
        position = position_of[cid]
        context = []
        for offset in range(-CONTEXT_WINDOW, CONTEXT_WINDOW + 1):
            index = position + offset
            if offset == 0 or not (0 <= index < len(order)):
                continue
            neighbour = by_id[order[index]]
            if neighbour["religion"] != record["religion"]:
                continue
            context.append({
                "canonical_id": neighbour["canonical_id"],
                "text": mv.display_text(neighbour)[0],
            })

        prior = priors.get(cid, {})
        items.append({
            "canonical_id": cid,
            "religion": record["religion"],
            "reference": reference_of(record),
            "text_source": text_ref,
            "verse_text": verse_text,
            "verse_text_sha256": mv.sha256_text(verse_text),
            "prior_features": prior.get("features", {}),
            "prior_flags": prior.get("flags", []),
            "source_annotations": [
                {
                    "source": a.get("source"),
                    "type": a.get("annotation_type"),
                    "value": a.get("value"),
                }
                for a in mv.independent_annotations(record)
            ],
            "context": context,
        })

    payload = {
        "taxonomy_version": taxonomy.version,
        "tier": args.tier,
        "total_in_tier": len(selected),
        "already_annotated": len(done),
        "still_pending": len(pending),
        "batch_size": len(items),
        "records": items,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(f"worklist -> {args.out}  ({len(items)} records, {len(pending)} pending)")
    else:
        print(text)
    return 0


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

def cmd_ingest(args: argparse.Namespace) -> int:
    taxonomy = mv.Taxonomy()
    by_id, _ = load_corpus()

    incoming = list(mv.read_jsonl(Path(args.batch)))
    if not incoming:
        print("batch is empty")
        return 1

    run_dir = RUNS_DIR / AGENT_RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    responses_path = run_dir / "responses.jsonl"
    rejects_path = run_dir / "rejects.jsonl"

    existing: dict[str, dict] = {}
    if responses_path.exists():
        for row in mv.read_jsonl(responses_path):
            existing[row["canonical_id"]] = row

    # a record annotated in a DIFFERENT run must not be duplicated here
    other_runs = annotated_ids() - set(existing)

    accepted, skipped = 0, 0
    rejected: list[dict] = []
    for response in incoming:
        cid = response.get("canonical_id")
        if cid not in by_id:
            rejected.append({"canonical_id": cid, "problems": ["canonical_id not in corpus"]})
            continue
        if cid in other_runs:
            skipped += 1
            continue

        verse_text, _ = mv.display_text(by_id[cid])
        response.setdefault("taxonomy_version", taxonomy.version)
        response.setdefault("verse_text_sha256", mv.sha256_text(verse_text))
        response["_annotator"] = ANNOTATOR
        response["_annotation_method"] = "agent_authored"

        problems = annotate.validate_response(response, cid, verse_text, taxonomy)
        if problems:
            # rejected, never repaired - the Phase 0 rule, unchanged
            rejected.append({"canonical_id": cid, "problems": problems})
            continue
        existing[cid] = response       # idempotent: replace, never append
        accepted += 1

    rows = [existing[cid] for cid in sorted(existing)]
    mv.write_jsonl(responses_path, rows)
    # A record that is already accepted is not a reject, even if a stale copy of
    # it was re-offered in this batch. Only genuinely unannotated ids are listed.
    mv.write_jsonl(rejects_path, [r for r in rejected if r["canonical_id"] not in existing])

    mv.write_json(run_dir / "run_manifest.json", {
        "run_id": AGENT_RUN_ID,
        "annotator": ANNOTATOR,
        "annotation_method": "agent_authored",
        "provenance_note": (
            "Annotations authored by the development agent during repository work, "
            "not obtained from a paid inference API. No scripture text was generated, "
            "corrected or paraphrased; every evidence_span is a verbatim substring of "
            "the Phase 0 text, enforced by annotate.validate_response."
        ),
        "api_calls": 0,
        "taxonomy_version": taxonomy.version,
        "context_window": CONTEXT_WINDOW,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "responses_accepted": len(rows),
        "responses_rejected_this_batch": len(rejected),
    })

    print(f"run {AGENT_RUN_ID}")
    print(f"  batch offered       {len(incoming):,}")
    print(f"  accepted            {accepted:,}")
    print(f"  rejected            {len(rejected):,}")
    print(f"  skipped (other run) {skipped:,}")
    print(f"  run total           {len(rows):,}")
    for reject in rejected[:10]:
        print(f"    ! {reject['canonical_id']}: {reject['problems'][:2]}")
    return 0 if not rejected else 1


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    done = annotated_ids()
    high_yield = annotate.select_records(None, None, "high_yield")
    everything = annotate.select_records(None, None, "all")
    hy_ids = {r["canonical_id"] for r in high_yield}

    by_religion: dict[str, int] = {}
    for record in everything:
        if record["canonical_id"] in done:
            by_religion[record["religion"]] = by_religion.get(record["religion"], 0) + 1

    print("annotation status")
    print(f"  annotated            {len(done):,}")
    print(f"    bible              {by_religion.get('bible', 0):,}")
    print(f"    quran              {by_religion.get('quran', 0):,}")
    print(f"  high_yield tier      {len(hy_ids):,}")
    print(f"    annotated          {len(hy_ids & done):,}")
    print(f"    remaining          {len(hy_ids - done):,}")
    print(f"  full corpus          {len(everything):,}")
    print(f"    remaining          {len(everything) - len(done):,}")
    return 0


def main() -> int:
    mv.setup_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    w = sub.add_parser("worklist", help="emit the next N unannotated records")
    w.add_argument("--limit", type=int, default=25)
    w.add_argument("--offset", type=int, default=0)
    w.add_argument("--religion", choices=("bible", "quran"))
    w.add_argument("--tier", choices=("all", "high_yield"), default="high_yield")
    w.add_argument("--out")
    w.set_defaults(func=cmd_worklist)

    i = sub.add_parser("ingest", help="validate and merge an authored batch")
    i.add_argument("batch")
    i.set_defaults(func=cmd_ingest)

    s = sub.add_parser("status", help="how many annotated, how many remain")
    s.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
