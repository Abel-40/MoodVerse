"""How a stored verse is presented. No database: rows are built in memory."""

from __future__ import annotations

from app.models.scripture import SURAH_NAMES, Scripture, format_reference
from app.schemas.reflection import VerseOut


def test_quran_references_carry_the_surah_name():
    assert len(SURAH_NAMES) == 114
    assert format_reference("quran", "Surah 94", 94, 5) == "Surah Ash-Sharh 94:5"
    assert format_reference("quran", "Surah 2", 2, 255) == "Surah Al-Baqarah 2:255"
    assert format_reference("bible", "Psalms", 34, 18) == "Psalms 34:18"


def test_verse_out_carries_the_arabic_verbatim_and_none_for_the_bible():
    ayah = Scripture(
        canonical_id="quran:94:5", religion="quran", book_or_surah="Surah 94", chapter=94,
        verse=5, text="For indeed, with hardship [will be] ease.",
        text_source="QSAC/Saheeh International", text_sha256="x",
        original_text="فَإِنَّ مَعَ الْعُسْرِ يُسْرًا", original_source="Complete_Quran_data",
    )
    verse = Scripture(
        canonical_id="bible:Psalms:34:18", religion="bible", book_or_surah="Psalms",
        chapter=34, verse=18, text="The LORD is near...", text_source="AKJV", text_sha256="y",
    )
    out = VerseOut.from_scripture(ayah)
    assert out.arabic == "فَإِنَّ مَعَ الْعُسْرِ يُسْرًا"
    assert out.translation == "Saheeh International"
    assert out.reference == "Surah Ash-Sharh 94:5"
    assert VerseOut.from_scripture(verse).arabic is None
