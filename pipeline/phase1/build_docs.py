"""Generate taxonomy/definitions.md and mappings/mapping_rules.md from the data.

Both documents are DERIVED. Editing them by hand is pointless: they are
regenerated from taxonomy.json and source_label_ledger.json, which is what keeps
the prose and the enforced vocabulary from drifting apart.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import mv_common as mv

DEFINITIONS = mv.ENRICHMENT / "taxonomy" / "definitions.md"
MAPPING_RULES = mv.ENRICHMENT / "mappings" / "mapping_rules.md"
CHANGELOG = mv.ENRICHMENT / "taxonomy" / "CHANGELOG.md"


def render_definitions(taxonomy: mv.Taxonomy) -> str:
    raw = taxonomy.raw
    axes = raw["axes"]
    out = [
        "# MoodVerse taxonomy - definitions",
        "",
        f"Version `{raw['taxonomy_version']}`. **Generated from `taxonomy.json` by "
        "`build_docs.py` - do not edit by hand.**",
        "",
        raw["description"],
        "",
        "## The two-axis emotion rule",
        "",
        axes["emotions"]["definition"],
        "",
        f"> {raw['design_notes']['two_axis_emotion_use']}",
        "",
        f"**Why:** {raw['design_notes']['why_this_matters']}",
        "",
    ]

    def bullets(title: str, items: list[str]) -> None:
        if items:
            out.append(f"**{title}**")
            out.append("")
            out.extend(f"- {i}" for i in items)
            out.append("")

    # A. emotions
    out += ["---", "", "## A. Emotions (17)", ""]
    bullets("Inclusion criteria", axes["emotions"]["inclusion_criteria"])
    bullets("Exclusion criteria", axes["emotions"]["exclusion_criteria"])
    out += ["| Value | Definition | Boundary |", "| --- | --- | --- |"]
    for value in axes["emotions"]["values"]:
        flag = " **[safety-critical]**" if value.get("safety_critical") else ""
        out.append(
            f"| `{value['id']}`{flag} | {value['definition']} | {value.get('boundary', '')} |"
        )
    out.append("")
    bullets("Documented ambiguities", axes["emotions"]["documented_ambiguities"])

    # C. intensity
    out += ["---", "", "## C. Intensity (1-4)", "",
            axes["intensity"]["scale_rationale"], "",
            axes["intensity"]["two_field_note"], "",
            "| Level | Name | Anchor |", "| ---: | --- | --- |"]
    for value in axes["intensity"]["values"]:
        out.append(f"| {value['id']} | `{value['label']}` | {value['anchor']} |")
    out.append("")

    # D. themes
    out += ["---", "", f"## D. Themes ({len(axes['themes']['values'])})", ""]
    bullets("Inclusion criteria", axes["themes"]["inclusion_criteria"])
    bullets("Exclusion criteria", axes["themes"]["exclusion_criteria"])
    groups = {g["id"]: g["label"] for g in axes["themes"]["groups"]}
    by_group: dict[str, list] = defaultdict(list)
    for value in axes["themes"]["values"]:
        by_group[value["group"]].append(value)
    for group_id, label in groups.items():
        out += [f"### {label}", "", "| Value | Definition |", "| --- | --- |"]
        for value in by_group[group_id]:
            note = f" *{value['boundary']}*" if value.get("boundary") else ""
            out.append(f"| `{value['id']}` | {value['definition']}{note} |")
        out.append("")

    # E. intents
    out += ["---", "", f"## E. Reflection intents ({len(axes['intents']['values'])})", "",
            axes["intents"]["definition"], "",
            "| Value | Definition | Distinguished from | Added |",
            "| --- | --- | --- | :---: |"]
    for value in axes["intents"]["values"]:
        added = "yes" if value.get("added_beyond_product_list") else ""
        out.append(
            f"| `{value['id']}` | {value['definition']} | "
            f"{value.get('distinguished_from', '')} | {added} |"
        )
    out.append("")
    added = [v for v in axes["intents"]["values"] if v.get("added_beyond_product_list")]
    if added:
        out += ["**Intents added beyond the product's original list, and why:**", ""]
        for value in added:
            out.append(f"- **`{value['id']}`** - {value['rationale']}")
        out.append("")

    # F. situations
    out += ["---", "", f"## F. Situations ({len(axes['situations']['values'])})", "",
            axes["situations"]["sparsity_note"], "",
            "| Value | Definition |", "| --- | --- |"]
    for value in axes["situations"]["values"]:
        note = f" *{value['note']}*" if value.get("note") else ""
        out.append(f"| `{value['id']}` | {value['definition']}{note} |")
    out.append("")

    # G. scripture purposes
    out += ["---", "", f"## G. Scripture purposes ({len(axes['scripture_purposes']['values'])})",
            "", axes["scripture_purposes"]["definition"], "",
            f"**Why this axis exists:** {axes['scripture_purposes']['why_this_axis_exists']}", "",
            "| Value | Definition | Context prior |", "| --- | --- | --- |"]
    for value in axes["scripture_purposes"]["values"]:
        flag = " **[safety-critical]**" if value.get("safety_critical") else ""
        out.append(
            f"| `{value['id']}`{flag} | {value['definition']} | "
            f"{value.get('context_dependency_prior', '')} |"
        )
    out.append("")
    for value in axes["scripture_purposes"]["values"]:
        if value.get("note"):
            out += [f"**`{value['id']}`** - {value['note']}", ""]
    for name, subfield in axes["scripture_purposes"]["subfields"].items():
        out += [f"### Subfield `{name}`", "", "| Value | Definition |", "| --- | --- |"]
        for value in subfield["values"]:
            flag = " **[hard exclusion trigger]**" if value.get("hard_exclusion_trigger") else ""
            out.append(f"| `{value['id']}`{flag} | {value['definition']} |")
        out.append("")

    # H. context dependency
    out += ["---", "", "## H. Context dependency (0-4)", "",
            axes["context_dependency"]["reasons_note"], "",
            "| Level | Name | Anchor |", "| ---: | --- | --- |"]
    for value in axes["context_dependency"]["values"]:
        out.append(f"| {value['id']} | `{value['label']}` | {value['anchor']} |")
    out += ["", "### Dependency reasons", "", "| Value | Definition |", "| --- | --- |"]
    for value in axes["context_dependency"]["dependency_reasons"]:
        out.append(f"| `{value['id']}` | {value['definition']} |")
    out.append("")

    # scales
    scales = axes["scales"]
    out += ["---", "", "## Scales", "", f"**Design rule.** {scales['design_rule']}", ""]
    for name in ("standalone_usefulness", "emotional_relevance", "purpose_suitability", "isolation_risk"):
        scale = scales[name]
        out += [f"### `{name}`", "", scale["definition"], ""]
        if scale.get("conditional_on"):
            out += [f"Conditional on: {scale['conditional_on']}.", ""]
        out += ["| Level | Name | Anchor |", "| ---: | --- | --- |"]
        for value in scale["values"]:
            extra = ""
            if value.get("purpose"):
                extra = f" **{value['purpose']}**"
            if value.get("hard_exclusion_trigger"):
                extra += " **[hard exclusion trigger]**"
            out.append(f"| {value['id']} | `{value['label']}` | {value['anchor']}{extra} |")
        out.append("")
        if scale.get("mandatory_blocker_rule"):
            out += [f"> {scale['mandatory_blocker_rule']}", ""]

    confidence = scales["curation_confidence"]
    out += ["### `curation_confidence`", "", confidence["definition"], "",
            f"> {confidence['note']}", "", "| Band | Evidence |", "| ---: | --- |"]
    for band in confidence["bands"]:
        out.append(f"| {band['value']} | {band['evidence']} |")
    out.append("")

    for name, key in (("Blockers", "blockers"), ("Content advisories", "content_advisories")):
        out += [f"### {name}", "", "| Value | Definition |", "| --- | --- |"]
        for value in scales[key]:
            out.append(f"| `{value['id']}` | {value['definition']} |")
        out.append("")

    # structural
    structural = axes["structural"]
    out += ["---", "", "## Structural vocabularies", "", structural["definition"], "",
            "### Annotation methods (ordered ladder)", "",
            "| Rank | Method | Meaning |", "| ---: | --- | --- |"]
    for value in structural["annotation_methods"]["values"]:
        out.append(f"| {value['rank']} | `{value['id']}` | {value['definition']} |")
    out += ["", f"> {structural['annotation_methods']['monotonicity_rule']}", "",
            "### Curation statuses", "", "| Status | Meaning |", "| --- | --- |"]
    for value in structural["curation_status"]["values"]:
        out.append(f"| `{value['id']}` | {value['definition']} |")
    out += ["", "### Evidence tiers", "",
            f"> {structural['evidence_tiers']['note']}", "",
            "| Tier | Weight | Sources | Justification |", "| --- | ---: | --- | --- |"]
    for value in structural["evidence_tiers"]["values"]:
        out.append(
            f"| `{value['id']}` | {value['weight']} | {', '.join(value['sources']) or '-'} | "
            f"{value['justification']} |"
        )
    out.append("")
    return "\n".join(out)


def render_mapping_rules(ledger: dict, quarantine: dict) -> str:
    rows = ledger["rows"]
    by_vocab: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        by_vocab[(row["source"], row["source_annotation_type"])].append(row)

    out = [
        "# Source-label mapping rules",
        "",
        f"Ledger schema `{ledger['ledger_schema_version']}`, taxonomy "
        f"`{ledger['taxonomy_version']}`. **Generated from `source_label_ledger.json` by "
        "`build_docs.py` - do not edit by hand.** The declared rules live in "
        "`processed/enrichment/ledger_rules.py`.",
        "",
        "## Policy",
        "",
    ]
    for key, value in ledger["policy"].items():
        if isinstance(value, str):
            out.append(f"- **{key.replace('_', ' ')}** - {value}")
        else:
            out.append(f"- **{key.replace('_', ' ')}** - `{', '.join(value)}`")
    out += [
        "",
        "## Totals",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Ledger rows | {ledger['totals']['rows']} |",
        f"| From independent sources | {ledger['totals']['rows_independent_sources']} |",
        f"| From derived sources (weight 0) | {ledger['totals']['rows_derived_sources']} |",
        f"| Quarantined | {ledger['totals']['quarantined']} |",
        "",
        "Targets by axis: "
        + ", ".join(f"`{k}` {v}" for k, v in ledger["totals"]["targets_by_axis"].items())
        + ".",
        "",
        "## Vocabularies",
        "",
        "| Source | Annotation type | Rows | Tier | Independent |",
        "| --- | --- | ---: | --- | :---: |",
    ]
    for (source, atype), vocab_rows in sorted(by_vocab.items()):
        first = vocab_rows[0]
        out.append(
            f"| {source} | {atype} | {len(vocab_rows)} | `{first['source_evidence_tier']}` | "
            f"{'yes' if first['independent_annotation_source'] else 'no'} |"
        )
    out += [
        "",
        "## Quarantine",
        "",
        quarantine["policy"],
        "",
        f"{quarantine['count']} labels are quarantined, all for `low_frequency` "
        f"(<= {quarantine['low_frequency_threshold']} occurrences).",
        "",
        "## Worked examples",
        "",
        "The three rows that show most clearly what the ledger is for.",
        "",
    ]
    highlights = [
        "complete_quran_data.emotion.fear",
        "complete_quran_data.theme_tag.fear",
        "complete_quran_data.context.makki_revelation",
    ]
    by_id = {r["mapping_id"]: r for r in rows}
    for mapping_id in highlights:
        row = by_id.get(mapping_id)
        if not row:
            continue
        targets = ", ".join(
            f"`{t['axis']}:{t['value']}` ({t['relation']}, {t['confidence']})"
            for t in row["targets"]
        )
        out += [
            f"### `{row['source_label']}` - {row['source']} / {row['source_annotation_type']} "
            f"({row['source_label_occurrences']:,} occurrences)",
            "",
            f"- targets: {targets}",
            f"- tier: `{row['source_evidence_tier']}` (weight {row['evidence_weight']})",
            f"- rationale: {row['rationale']}",
            "",
        ]
    return "\n".join(out)


def render_changelog(taxonomy: mv.Taxonomy) -> str:
    axes = taxonomy.raw["axes"]
    return "\n".join([
        "# Taxonomy changelog",
        "",
        "## 1.0.0",
        "",
        "First version. Created in Phase 1B from the design in `PHASE1A_DESIGN.md`.",
        "",
        "| Axis | Values |",
        "| --- | ---: |",
        f"| Emotions | {len(axes['emotions']['values'])} |",
        f"| Intensity levels | {len(axes['intensity']['values'])} |",
        f"| Themes | {len(axes['themes']['values'])} |",
        f"| Reflection intents | {len(axes['intents']['values'])} |",
        f"| Situations | {len(axes['situations']['values'])} |",
        f"| Scripture purposes | {len(axes['scripture_purposes']['values'])} |",
        f"| Context dependency levels | {len(axes['context_dependency']['values'])} |",
        f"| Dependency reasons | {len(axes['context_dependency']['dependency_reasons'])} |",
        f"| Blockers | {len(axes['scales']['blockers'])} |",
        f"| Content advisories | {len(axes['scales']['content_advisories'])} |",
        "",
        "### Versioning policy",
        "",
        *(f"- **{k}** - {v}" for k, v in taxonomy.raw["versioning_policy"].items()),
        "",
    ])


def main() -> int:
    mv.setup_stdout()
    before = mv.phase0_digests()
    taxonomy = mv.Taxonomy()
    ledger = mv.read_json(mv.ENRICHMENT / "mappings" / "source_label_ledger.json")
    quarantine = mv.read_json(mv.ENRICHMENT / "mappings" / "quarantine.json")

    mv.write_text(DEFINITIONS, render_definitions(taxonomy))
    mv.write_text(MAPPING_RULES, render_mapping_rules(ledger, quarantine))
    mv.write_text(CHANGELOG, render_changelog(taxonomy))
    mv.assert_phase0_unchanged(before, mv.phase0_digests())

    for path in (DEFINITIONS, MAPPING_RULES, CHANGELOG):
        print(f"  {path.relative_to(mv.BASE)}  ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
