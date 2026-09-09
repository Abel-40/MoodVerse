"""Gemini annotation harness. The ONLY file in Phase 1 that makes network calls.

Contract, in one sentence: Gemini interprets text it is GIVEN. It never supplies
scripture, and it never decides a curation status.

Responses are recorded to annotation/runs/<run_id>/ and replayed by
build_enrichment.py, which stays a pure function. A re-run creates a NEW run_id
and a reviewable diff; it never overwrites in place.

A malformed response is rejected and retried once, then the record is left for
review. It is NEVER programmatically repaired - repair is silent
reinterpretation, which is exactly what Phase 0 refused to do.

Credentials: set GEMINI_API_KEY in the environment, or put it in the gitignored
repo-root .env as GEMINI_API_KEY=... . The key is never logged or written into
any artefact.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import mv_common as mv

RUNS_DIR = mv.ENRICHMENT / "annotation" / "runs"
PROMPTS_DIR = mv.ENRICHMENT / "annotation" / "prompts"
PRIORS = mv.ENRICHMENT / "priors" / "deterministic_priors.jsonl"

DEFAULT_MODEL = "gemini-2.5-pro"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# Verses on either side supplied as context. Identical for both religions - the
# annotation path must not differ by corpus.
CONTEXT_WINDOW = 3

# Anything that looks like a scripture citation. Used to reject invented
# references in free-text fields.
REFERENCE_RE = re.compile(
    r"\b\d+\s*:\s*\d+\b|\b(?:Genesis|Exodus|Psalm|Psalms|Isaiah|Matthew|Mark|Luke|John|Romans|"
    r"Surah|Quran|Qur'an|Ayah)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# credentials
# ---------------------------------------------------------------------------

def load_api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key.strip()
    env_file = mv.BASE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return None


# ---------------------------------------------------------------------------
# response schema, generated from the taxonomy so the two cannot drift
# ---------------------------------------------------------------------------

def response_schema(taxonomy: mv.Taxonomy) -> dict:
    def enum(values) -> dict:
        return {"type": "STRING", "enum": sorted(values)}

    def score() -> dict:
        return {"type": "INTEGER"}

    return {
        "type": "OBJECT",
        "properties": {
            "canonical_id": {"type": "STRING"},
            "verse_text_sha256": {"type": "STRING"},
            "taxonomy_version": {"type": "STRING"},
            "expressed_affect": {
                "type": "OBJECT",
                "properties": {
                    "primary": enum(taxonomy.emotions),
                    "secondary": {"type": "ARRAY", "items": enum(taxonomy.emotions)},
                    "text_intensity": score(),
                },
                "required": ["primary", "text_intensity"],
            },
            "addressed_states": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "state": enum(taxonomy.emotions),
                        "emotional_relevance": score(),
                        "evidence_span": {"type": "STRING"},
                    },
                    "required": ["state", "emotional_relevance", "evidence_span"],
                },
            },
            "serves_intensity": {
                "type": "OBJECT",
                "properties": {"min": score(), "max": score()},
                "required": ["min", "max"],
            },
            "nuance_terms": {"type": "ARRAY", "items": {"type": "STRING"}},
            "themes": {"type": "ARRAY", "items": enum(taxonomy.themes)},
            "intents": {"type": "ARRAY", "items": enum(taxonomy.intents)},
            "scripture_purpose": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "purpose": enum(taxonomy.scripture_purposes),
                        "speaker_role": enum(taxonomy.speaker_roles),
                        "promise_conditionality": enum(taxonomy.promise_conditionality),
                    },
                    "required": ["purpose"],
                },
            },
            "situations": {"type": "ARRAY", "items": enum(taxonomy.situations)},
            "standalone_usefulness": score(),
            "context_dependency": {
                "type": "OBJECT",
                "properties": {
                    "level": score(),
                    "reasons": {"type": "ARRAY", "items": enum(taxonomy.dependency_reasons)},
                },
                "required": ["level", "reasons"],
            },
            "recommended_context_span": {
                "type": "OBJECT",
                "properties": {
                    "start_canonical_id": {"type": "STRING"},
                    "end_canonical_id": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                },
            },
            "isolation_risk": {
                "type": "OBJECT",
                "properties": {
                    "level": score(),
                    "kinds": {"type": "ARRAY", "items": enum(taxonomy.isolation_kinds)},
                    "explanation": {"type": "STRING"},
                },
                "required": ["level", "kinds"],
            },
            "purpose_suitability": {
                "type": "OBJECT",
                "properties": {
                    intent: {
                        "type": "OBJECT",
                        "properties": {
                            "score": score(),
                            "basis": {"type": "STRING"},
                            "blockers": {"type": "ARRAY", "items": enum(taxonomy.blockers)},
                        },
                        "required": ["score", "basis", "blockers"],
                    }
                    for intent in sorted(taxonomy.intents)
                },
            },
            "safety": {
                "type": "OBJECT",
                "properties": {
                    "crisis_safe": {"type": "BOOLEAN"},
                    "avoid_for_states": {"type": "ARRAY", "items": enum(taxonomy.emotions)},
                    "content_advisories": {
                        "type": "ARRAY", "items": enum(taxonomy.content_advisories)
                    },
                },
                "required": ["crisis_safe", "avoid_for_states", "content_advisories"],
            },
            "source_disagreements": {"type": "ARRAY", "items": {"type": "STRING"}},
            "theologically_contested": {"type": "BOOLEAN"},
            "model_rationale": {"type": "STRING"},
            "self_reported_uncertainty": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": [
            "canonical_id", "verse_text_sha256", "taxonomy_version", "expressed_affect",
            "addressed_states", "themes", "intents", "scripture_purpose",
            "standalone_usefulness", "context_dependency", "isolation_risk",
            "purpose_suitability", "safety", "theologically_contested", "model_rationale",
        ],
    }


# ---------------------------------------------------------------------------
# validation - reject and retry, never repair
# ---------------------------------------------------------------------------

def validate_response(
    response: dict, canonical_id: str, verse_text: str, taxonomy: mv.Taxonomy | None = None
) -> list[str]:
    """Return a list of violations. Empty list means the response is acceptable."""
    problems: list[str] = []

    if response.get("canonical_id") != canonical_id:
        problems.append(
            f"canonical_id mismatch: got {response.get('canonical_id')!r}, sent {canonical_id!r}"
        )

    expected_hash = mv.sha256_text(verse_text)
    if "verse_text_sha256" in response and response["verse_text_sha256"] != expected_hash:
        problems.append("verse_text_sha256 does not match the text supplied")

    # every evidence_span must be a verbatim substring of the supplied verse
    for state in response.get("addressed_states") or []:
        span = (state.get("evidence_span") or "").strip()
        if span and span not in verse_text:
            problems.append(
                f"evidence_span not present verbatim in the supplied verse: {span[:60]!r}"
            )

    # no scripture references in free text
    free_text = [response.get("model_rationale") or ""]
    for block in (response.get("purpose_suitability") or {}).values():
        free_text.append((block or {}).get("basis") or "")
    free_text.append((response.get("isolation_risk") or {}).get("explanation") or "")
    for text in free_text:
        if REFERENCE_RE.search(text):
            problems.append(f"free-text field contains a scripture reference: {text[:60]!r}")
            break

    # ordinal ranges
    def in_range(value, low, high, label):
        if value is not None and not (isinstance(value, int) and low <= value <= high):
            problems.append(f"{label} out of range: {value!r}")

    in_range(response.get("standalone_usefulness"), 0, 4, "standalone_usefulness")
    in_range((response.get("context_dependency") or {}).get("level"), 0, 4, "context_dependency")
    in_range((response.get("isolation_risk") or {}).get("level"), 0, 3, "isolation_risk")
    in_range((response.get("expressed_affect") or {}).get("text_intensity"), 1, 4, "text_intensity")
    for state in response.get("addressed_states") or []:
        in_range(state.get("emotional_relevance"), 0, 4, f"relevance[{state.get('state')}]")
    for intent, block in (response.get("purpose_suitability") or {}).items():
        in_range((block or {}).get("score"), 0, 4, f"suitability[{intent}]")

    # conditional requirements
    context = response.get("context_dependency") or {}
    if (context.get("level") or 0) >= 2 and not context.get("reasons"):
        problems.append("context_dependency >= 2 requires dependency reasons")

    isolation = response.get("isolation_risk") or {}
    if (isolation.get("level") or 0) >= 2 and not (isolation.get("explanation") or "").strip():
        problems.append("isolation_risk >= 2 requires an explanation")

    for purpose in response.get("scripture_purpose") or []:
        if purpose.get("purpose") == "reported_speech" and not purpose.get("speaker_role"):
            problems.append("reported_speech requires a speaker_role")

    max_relevance = max(
        [s.get("emotional_relevance") or 0 for s in (response.get("addressed_states") or [])],
        default=0,
    )
    if max_relevance >= 3:
        for intent, block in (response.get("purpose_suitability") or {}).items():
            block = block or {}
            if (block.get("score") or 0) <= 1 and not block.get("blockers"):
                problems.append(
                    f"relevance {max_relevance} with suitability {block.get('score')} for "
                    f"`{intent}` requires at least one blocker"
                )
                break

    if taxonomy is not None:
        if response.get("taxonomy_version") != taxonomy.version:
            problems.append(
                f"taxonomy_version {response.get('taxonomy_version')!r} != {taxonomy.version!r}"
            )
        for theme in response.get("themes") or []:
            if theme not in taxonomy.themes:
                problems.append(f"unknown theme {theme!r}")
        for intent in response.get("intents") or []:
            if intent not in taxonomy.intents:
                problems.append(f"unknown intent {intent!r}")

    return problems


# ---------------------------------------------------------------------------
# prompt construction
# ---------------------------------------------------------------------------

def build_prompt(
    record: dict, verse_text: str, context: list[tuple[str, str]], prior_row: dict,
    taxonomy: mv.Taxonomy, blind: bool,
) -> str:
    template = (PROMPTS_DIR / "annotate_verse.md").read_text(encoding="utf-8")

    context_block = "\n".join(
        f"  [{cid}] {text}" for cid, text in context
    ) or "  (none - this verse has no neighbours in the corpus)"

    if blind:
        source_block = (
            "  (withheld - this request is running in BLIND MODE for asymmetry calibration)"
        )
    else:
        labels = [
            f"  - {a['source']} / {a['annotation_type']}: {a['value']}"
            for a in mv.independent_annotations(record)
        ]
        source_block = "\n".join(labels) or "  (none - this verse carries no source annotation)"

    prior_block = "\n".join(
        f"  - {p['rule_id']} ({p['nudge']:+d} to {p['field']}): {p['basis']}"
        for p in prior_row.get("priors", [])
    ) or "  (none)"

    return (
        template
        .replace("{{CANONICAL_ID}}", record["canonical_id"])
        .replace("{{RELIGION}}", record["religion"])
        .replace("{{TAXONOMY_VERSION}}", taxonomy.version)
        .replace("{{VERSE_TEXT}}", verse_text)
        .replace("{{VERSE_SHA256}}", mv.sha256_text(verse_text))
        .replace("{{CONTEXT_BLOCK}}", context_block)
        .replace("{{SOURCE_ANNOTATIONS}}", source_block)
        .replace("{{DETERMINISTIC_PRIORS}}", prior_block)
    )


def call_gemini(prompt: str, schema: dict, model: str, api_key: str, timeout: int = 120) -> dict:
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }
    request = urllib.request.Request(
        f"{API_ROOT}/{model}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as handle:
        body = json.loads(handle.read().decode("utf-8"))
    text = body["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


# ---------------------------------------------------------------------------

def select_records(limit: int | None, religion: str | None, tier: str) -> list[dict]:
    """Tiered rollout: prove the pipeline on high-yield records first."""
    priors = {row["canonical_id"]: row for row in mv.read_jsonl(PRIORS)}
    selected = []
    for record in mv.iter_corpus():
        if religion and record["religion"] != religion:
            continue
        if tier == "high_yield":
            features = priors.get(record["canonical_id"], {}).get("features", {})
            if record["religion"] == "bible":
                if features.get("genre") not in ("poetry_wisdom", "epistle"):
                    continue
                if features.get("opens_with_connective") or features.get("opens_with_pronoun"):
                    continue
        selected.append(record)
        if limit and len(selected) >= limit:
            break
    return selected


def main() -> int:
    mv.setup_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="annotate at most N records")
    parser.add_argument("--religion", choices=("bible", "quran"))
    parser.add_argument("--tier", choices=("all", "high_yield"), default="high_yield")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--blind", action="store_true",
                        help="withhold source annotations, for asymmetry calibration")
    parser.add_argument("--run-id", help="defaults to a UTC timestamp")
    parser.add_argument("--dry-run", action="store_true",
                        help="write requests.jsonl and exit without calling the API")
    args = parser.parse_args()

    taxonomy = mv.Taxonomy()
    schema = response_schema(taxonomy)
    api_key = load_api_key()
    if not api_key and not args.dry_run:
        print("No GEMINI_API_KEY found in the environment or the repo-root .env.")
        print("Set it, or use --dry-run to generate requests without calling the API.")
        return 2

    run_id = args.run_id or dt.datetime.now(dt.timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    records = select_records(args.limit, args.religion, args.tier)
    by_id = {r["canonical_id"]: r for r in mv.iter_corpus()}
    order = list(by_id)
    # precomputed so context assembly is O(1) per record rather than O(n): a
    # list .index() lookup here would make a full 37k run quadratic.
    position_of = {cid: i for i, cid in enumerate(order)}
    priors = {row["canonical_id"]: row for row in mv.read_jsonl(PRIORS)}

    template_path = PROMPTS_DIR / "annotate_verse.md"
    manifest = {
        "run_id": run_id,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model": args.model,
        "temperature": 0,
        "blind_mode": args.blind,
        "tier": args.tier,
        "religion_filter": args.religion,
        "taxonomy_version": taxonomy.version,
        "prompt_template": template_path.name,
        "prompt_template_sha256": mv.sha256_file(template_path),
        "context_window": CONTEXT_WINDOW,
        "records_selected": len(records),
        "dry_run": args.dry_run,
    }

    requests_out, responses_out, rejects_out = [], [], []
    for index, record in enumerate(records):
        cid = record["canonical_id"]
        verse_text, _ = mv.display_text(record)
        position = position_of[cid]
        context = []
        for offset in range(-CONTEXT_WINDOW, CONTEXT_WINDOW + 1):
            if offset == 0 or not (0 <= position + offset < len(order)):
                continue
            neighbour = by_id[order[position + offset]]
            if neighbour["religion"] != record["religion"]:
                continue
            context.append((neighbour["canonical_id"], mv.display_text(neighbour)[0]))

        prompt = build_prompt(record, verse_text, context, priors.get(cid, {}), taxonomy, args.blind)
        requests_out.append(
            {
                "canonical_id": cid,
                "religion": record["religion"],
                "verse_text_sha256": mv.sha256_text(verse_text),
                "prompt_sha256": mv.sha256_text(prompt),
                "blind_mode": args.blind,
            }
        )
        if args.dry_run:
            continue

        for attempt in (1, 2):
            try:
                response = call_gemini(prompt, schema, args.model, api_key)
            except (urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
                if attempt == 2:
                    rejects_out.append({"canonical_id": cid, "attempt": attempt,
                                        "error": f"{type(exc).__name__}: {exc}"})
                time.sleep(2)
                continue
            problems = validate_response(response, cid, verse_text, taxonomy)
            if not problems:
                response["_run_id"] = run_id
                responses_out.append(response)
                break
            rejects_out.append(
                {"canonical_id": cid, "attempt": attempt, "problems": problems,
                 "raw_response": response}
            )
            if attempt == 2:
                # left for review; never repaired
                pass
        if (index + 1) % 25 == 0:
            print(f"  {index + 1}/{len(records)} annotated, {len(rejects_out)} rejects")

    manifest["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest["responses_accepted"] = len(responses_out)
    manifest["responses_rejected"] = len(rejects_out)

    mv.write_jsonl(run_dir / "requests.jsonl", requests_out)
    mv.write_jsonl(run_dir / "responses.jsonl", responses_out)
    mv.write_jsonl(run_dir / "rejects.jsonl", rejects_out)
    mv.write_json(run_dir / "run_manifest.json", manifest)

    print(f"run {run_id} -> {run_dir.relative_to(mv.BASE)}")
    print(f"  selected  {len(records):,}")
    print(f"  accepted  {len(responses_out):,}")
    print(f"  rejected  {len(rejects_out):,}")
    if args.dry_run:
        print("  DRY RUN - no API calls were made; run build_enrichment.py after a real run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
