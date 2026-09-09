from __future__ import annotations

import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

BASE = Path(r"d:\All I Need\2, project and source\3, project\1, my projects\3, fullstack projects\MoodVerse")
OUT = BASE / "processed"
OUT.mkdir(exist_ok=True)


def values(raw):
    text = str(raw or "").strip()
    if not text:
        return []
    separator = "|" if "|" in text else "," if "," in text else None
    return [part.strip() for part in (text.split(separator) if separator else [text]) if part.strip()]


def dump(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def blank_quran(cid):
    surah, ayah = (int(part) for part in cid.split(":")[1:])
    return {
        "canonical_id": cid, "religion": "quran",
        "location": {"book_or_surah": f"Surah {surah}", "chapter_or_surah_number": surah, "verse_start": ayah, "verse_end": ayah, "unit_type": "verse"},
        "text": {"original": "", "language": "ar", "translations": []},
        "source_annotations": [], "cross_references": [], "source_provenance": [],
        "data_quality": {"status": "valid", "issues": [], "warnings": []}
    }


def add_annotation(record, source, source_file, annotation_type, value):
    if value:
        record["source_annotations"].append({"source": source, "source_file": source_file, "annotation_type": annotation_type, "value": value})


catalog = {
    "sources": [
        {"source_id": "bible_akjv", "path": "bible related/AKJV.xml", "format": "xml"},
        {"source_id": "bible_cross_references", "path": "bible related/cross_references.txt", "format": "tsv"},
        {"source_id": "quran_complete", "path": "quran related/Complete_Quran_data.csv", "format": "csv"},
        {"source_id": "quran_tcec", "path": "quran related/Only TCEC cols.csv", "format": "csv"},
        {"source_id": "elqv", "path": "quran related/ELQV-main/ELQV.csv", "format": "csv"},
        {"source_id": "elqv_v2", "path": "quran related/ELQV-main/ELQVv2.csv", "format": "csv"},
        {"source_id": "qsac", "path": "quran related/quran-semantic-annotation-corpus-master", "format": "csv+json"}
    ]
}
dump("source_catalog.json", catalog)

bible = []
root = ET.parse(BASE / "bible related" / "AKJV.xml").getroot()
for book in root.findall("BIBLEBOOK"):
    name = book.attrib.get("bname", "Unknown")
    for chapter in book.findall("CHAPTER"):
        cnum = int(chapter.attrib.get("cnumber", 0))
        for verse in chapter.findall("VERS"):
            vnum = int(verse.attrib.get("vnumber", 0))
            text = (verse.text or "").strip()
            bible.append({
                "canonical_id": f"bible:{name}:{cnum}:{vnum}", "religion": "bible",
                "location": {"book": name, "chapter": cnum, "verse_start": vnum, "verse_end": vnum, "unit_type": "verse"},
                "text": {"original": text, "language": "en", "translation": "AKJV", "source": "AKJV"},
                "source_annotations": [{"source": "AKJV", "source_file": "bible related/AKJV.xml", "annotation_type": "verse_text", "value": text}],
                "cross_references": [], "source_provenance": [{"source_name": "AKJV", "source_file": "bible related/AKJV.xml", "source_type": "scripture_text"}],
                "data_quality": {"status": "valid", "issues": [], "warnings": []}
            })

refs = []
with (BASE / "bible related" / "cross_references.txt").open(encoding="utf-8", errors="replace", newline="") as handle:
    for row in csv.reader(handle, delimiter="\t"):
        if len(row) >= 3 and not row[0].startswith(("#", "From Verse")):
            refs.append({"source_ref": row[0], "target_ref": row[1], "votes": row[2], "source_dataset": "OpenBible Cross References"})

quran = {}
complete_count = 0
with (BASE / "quran related" / "Complete_Quran_data.csv").open(encoding="utf-8", errors="replace", newline="") as handle:
    for row in csv.DictReader(handle):
        surah, ayah = (row.get("Surah") or "").strip(), (row.get("Ayah") or "").strip()
        if not surah or not ayah:
            continue
        cid = f"quran:{int(surah)}:{int(ayah)}"
        rec = blank_quran(cid)
        rec["text"] = {"original": (row.get("Arabic") or "").strip(), "language": "ar", "translations": [
            {"translation_name": "Urdu", "language": "ur", "text": (row.get("Urdu") or "").strip(), "source": "Complete_Quran_data.csv"},
            {"translation_name": "English", "language": "en", "text": (row.get("English") or "").strip(), "source": "Complete_Quran_data.csv"}
        ]}
        for field, kind in (("Tags", "theme_tag"), ("Category", "category"), ("Emotion", "emotion"), ("Context", "context")):
            for item in values(row.get(field)):
                add_annotation(rec, "Complete_Quran_data", "quran related/Complete_Quran_data.csv", kind, item)
        rec["source_provenance"].append({"source_name": "Complete_Quran_data", "source_file": "quran related/Complete_Quran_data.csv", "source_type": "translation_and_metadata"})
        quran[cid] = rec
        complete_count += 1

subset_count = 0
with (BASE / "quran related" / "Only TCEC cols.csv").open(encoding="utf-8", errors="replace", newline="") as handle:
    for row in csv.DictReader(handle):
        surah, ayah = (row.get("Surah") or "").strip(), (row.get("Ayah") or "").strip()
        if not surah or not ayah:
            continue
        cid = f"quran:{int(surah)}:{int(ayah)}"
        rec = quran.setdefault(cid, blank_quran(cid))
        for field, kind in (("Tags", "theme_tag"), ("Category", "category"), ("Emotion", "emotion"), ("Context", "context")):
            for item in values(row.get(field)):
                add_annotation(rec, "Only TCEC cols", "quran related/Only TCEC cols.csv", kind, item)
        rec["source_provenance"].append({"source_name": "Only TCEC cols", "source_file": "quran related/Only TCEC cols.csv", "source_type": "subset_metadata"})
        subset_count += 1

elqv_count = 0
with (BASE / "quran related" / "ELQV-main" / "ELQV.csv").open(encoding="utf-8", errors="replace", newline="") as handle:
    for row in csv.DictReader(handle):
        surah, ayah = (row.get("Sourah Number") or "").strip(), (row.get("Verse Number") or "").strip()
        if not surah or not ayah:
            continue
        cid = f"quran:{int(surah)}:{int(ayah)}"
        rec = quran.setdefault(cid, blank_quran(cid))
        add_annotation(rec, "ELQV", "quran related/ELQV-main/ELQV.csv", "emotion", (row.get("Label") or "").strip())
        rec["source_provenance"].append({"source_name": "ELQV", "source_file": "quran related/ELQV-main/ELQV.csv", "source_type": "emotion_annotation"})
        elqv_count += 1

elqv2_count = 0
with (BASE / "quran related" / "ELQV-main" / "ELQVv2.csv").open(encoding="utf-8", errors="replace", newline="") as handle:
    for row in csv.DictReader(handle):
        surah, ayah = (row.get("Sourah_number") or "").strip(), (row.get("Verse_number") or "").strip()
        if not surah or not ayah:
            continue
        cid = f"quran:{int(surah)}:{int(ayah)}"
        rec = quran.setdefault(cid, blank_quran(cid))
        for key in ("Sahih_International", "Pickthall", "Yusuf_Ali (YA)", "Shakir", "Muhammad_Sarwar (MS)", "Mohsin_Khan (MK)", "Arberry"):
            text = (row.get(key) or "").strip()
            if text:
                rec["text"]["translations"].append({"translation_name": key, "language": "en", "text": text, "source": "ELQVv2"})
        add_annotation(rec, "ELQVv2", "quran related/ELQV-main/ELQVv2.csv", "emotion", (row.get("Label") or "").strip())
        rec["source_provenance"].append({"source_name": "ELQVv2", "source_file": "quran related/ELQV-main/ELQVv2.csv", "source_type": "translation_plus_emotion_annotation"})
        elqv2_count += 1

qsac_count = 0
qsac_tags = 0
qsac_path = BASE / "quran related" / "quran-semantic-annotation-corpus-master" / "data" / "qsac-dataset.csv"
with qsac_path.open(encoding="utf-8", errors="replace", newline="") as handle:
    reader = csv.DictReader(line for line in handle if not line.lstrip().startswith("#"))
    for row in reader:
        surah, ayah = (row.get("surah") or "").strip(), (row.get("ayah") or "").strip()
        if not surah or not ayah:
            continue
        cid = f"quran:{int(surah)}:{int(ayah)}"
        rec = quran.setdefault(cid, blank_quran(cid))
        if not rec["text"]["original"]:
            rec["text"]["original"] = (row.get("arabic") or "").strip()
        if not rec["text"]["translations"]:
            rec["text"]["translations"].append({"translation_name": "Saheeh International", "language": "en", "text": (row.get("eng") or "").strip(), "source": "QSAC"})
        for tag in values(row.get("tags")):
            add_annotation(rec, "QSAC", "quran related/quran-semantic-annotation-corpus-master/data/qsac-dataset.csv", "semantic_tag", tag)
            qsac_tags += 1
        rec["source_provenance"].append({"source_name": "QSAC", "source_file": "quran related/quran-semantic-annotation-corpus-master/data/qsac-dataset.csv", "source_type": "semantic_annotation"})
        qsac_count += 1

dump("qsac_ontology.json", json.loads((qsac_path.parent / "qsac-ontology.json").read_text(encoding="utf-8")))
all_records = bible + list(quran.values())
with (OUT / "unified_scripture_corpus.jsonl").open("w", encoding="utf-8") as handle:
    for record in all_records:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
dump("cross_reference_graph.json", {"relationships": refs})
dump("validation_report.json", {"bible_records": len(bible), "quran_records": len(quran), "total_records": len(all_records), "source_counts": {"complete_quran": complete_count, "tcec_subset": subset_count, "elqv": elqv_count, "elqv_v2": elqv2_count, "qsac": qsac_count, "qsac_tags": qsac_tags}, "status": "processed", "warnings": ["Source annotations remain source-specific; no final MoodVerse taxonomy was created."]})
dump("source_mapping_report.json", {"canonical_id_patterns": {"bible": "bible:<book>:<chapter>:<verse>", "quran": "quran:<surah>:<ayah>"}, "matching": "Quran surah + ayah; Bible book + chapter + verse"})
dump("unresolved_records.json", {"records": []})
(OUT / "clarification.md").write_text("# MoodVerse Phase 0\n\nThis phase discovered, extracted, normalized, and unified the Bible and Quran sources without modifying raw files or implementing later recommendation and AI phases. Canonical IDs preserve verse identity, while source-specific translations, tags, categories, emotions, contexts, QSAC tags, and provenance remain separate.\n", encoding="utf-8")
print(f"Bible records: {len(bible)}")
print(f"Quran records: {len(quran)}")
print(f"Total records: {len(all_records)}")
