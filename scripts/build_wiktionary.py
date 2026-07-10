from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from common import (
    create_database,
    database_counts,
    find_source_file,
    finalize_database,
    insert_metadata,
    json_text,
    normalize_word,
    open_text_auto,
    read_source_metadata,
    utc_now,
)

RELATION_FIELDS = {
    "synonyms": "synonym",
    "antonyms": "antonym",
    "hypernyms": "hypernym",
    "hyponyms": "hyponym",
    "meronyms": "meronym",
    "holonyms": "holonym",
    "related": "related",
    "derived": "derived",
}


def first_ipa(record: dict[str, Any]) -> str | None:
    for sound in record.get("sounds") or []:
        if isinstance(sound, dict) and sound.get("ipa"):
            return str(sound["ipa"])
    return None


def relation_words(value: Any) -> list[str]:
    result: list[str] = []
    for item in value or []:
        if isinstance(item, str):
            word = item
        elif isinstance(item, dict):
            word = item.get("word") or item.get("english") or item.get("name")
        else:
            word = None
        if word and str(word).strip():
            result.append(str(word).strip())
    return result


def headword_allowed(pack: dict[str, Any], normalized_headword: str) -> bool:
    """Apply an optional initial-letter shard filter."""
    shard = pack.get("headword_shard")
    if not shard:
        return True
    first = normalized_headword[:1]
    ascii_initials = set("abcdefghijklmnopqrstuvwxyz")
    if shard.get("other"):
        return not first or first not in ascii_initials
    initials = set(str(shard.get("initials", "")).casefold())
    if not initials:
        raise ValueError(f"{pack.get('id')}: headword_shard requires initials or other=true")
    return first in initials


def build(pack: dict[str, Any], source_dir: Path, stage_dir: Path, limit: int | None = None) -> dict[str, Any]:
    source_file = find_source_file(source_dir)
    db_path = stage_dir / "dictionary.sqlite"
    connection = create_database(db_path)
    source_language = pack["source_language"]
    definition_language = pack["definition_language"]
    inserted = 0
    processed = 0

    try:
        connection.execute("BEGIN")
        with open_text_auto(source_file) as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"Invalid JSONL at line {line_number}: {error}") from error

                processed += 1
                lang_code = record.get("lang_code") or record.get("language_code")
                if lang_code and lang_code != source_language:
                    continue
                headword = str(record.get("word") or "").strip()
                senses = record.get("senses") or []
                if not headword or not senses:
                    continue
                normalized_headword = normalize_word(headword, source_language)
                if not headword_allowed(pack, normalized_headword):
                    continue

                definitions: list[tuple[dict[str, Any], str]] = []
                for sense in senses:
                    if not isinstance(sense, dict):
                        continue
                    glosses = sense.get("glosses") or sense.get("raw_glosses") or []
                    if isinstance(glosses, str):
                        glosses = [glosses]
                    definition = " — ".join(
                        str(gloss).strip() for gloss in glosses if str(gloss).strip()
                    )
                    if definition:
                        definitions.append((sense, definition))
                if not definitions:
                    continue

                cursor = connection.execute(
                    """
                    INSERT INTO entries(
                        headword, normalized_headword, language_code,
                        definition_language_code, part_of_speech, pronunciation,
                        etymology, source_entry_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        headword,
                        normalized_headword,
                        source_language,
                        definition_language,
                        record.get("pos"),
                        first_ipa(record),
                        record.get("etymology_text"),
                        str(record.get("id") or record.get("etymology_number") or "") or None,
                    ),
                )
                entry_id = int(cursor.lastrowid)

                for sense_order, (sense, definition) in enumerate(definitions, start=1):
                    sense_cursor = connection.execute(
                        """
                        INSERT INTO senses(entry_id, sense_order, definition, tags_json, topics_json)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            entry_id,
                            sense_order,
                            definition,
                            json_text(sense.get("tags") or sense.get("raw_tags")),
                            json_text(sense.get("topics") or sense.get("categories")),
                        ),
                    )
                    sense_id = int(sense_cursor.lastrowid)
                    for example in sense.get("examples") or []:
                        if isinstance(example, str):
                            text, translation, reference = example, None, None
                        elif isinstance(example, dict):
                            text = example.get("text") or example.get("example")
                            translation = example.get("translation")
                            reference = example.get("ref") or example.get("roman")
                        else:
                            continue
                        if text and str(text).strip():
                            connection.execute(
                                """
                                INSERT INTO examples(sense_id, example_text, translation, reference_text)
                                VALUES (?, ?, ?, ?)
                                """,
                                (sense_id, str(text).strip(), translation, reference),
                            )

                    for source_field, relation_type in RELATION_FIELDS.items():
                        for related in relation_words(sense.get(source_field)):
                            connection.execute(
                                """
                                INSERT INTO relations(entry_id, relation_type, related_word, normalized_related_word)
                                VALUES (?, ?, ?, ?)
                                """,
                                (
                                    entry_id,
                                    relation_type,
                                    related,
                                    normalize_word(related, source_language),
                                ),
                            )

                for form in record.get("forms") or []:
                    if isinstance(form, str):
                        value, tags = form, None
                    elif isinstance(form, dict):
                        value, tags = form.get("form"), form.get("tags")
                    else:
                        continue
                    if value and str(value).strip() and str(value).strip() != headword:
                        value = str(value).strip()
                        connection.execute(
                            """
                            INSERT INTO forms(entry_id, form, normalized_form, tags_json)
                            VALUES (?, ?, ?, ?)
                            """,
                            (entry_id, value, normalize_word(value, source_language), json_text(tags)),
                        )

                for translation in record.get("translations") or []:
                    if not isinstance(translation, dict):
                        continue
                    translated = translation.get("word") or translation.get("translation")
                    if translated and str(translated).strip():
                        connection.execute(
                            """
                            INSERT INTO translations(
                                entry_id, sense_text, target_language_code,
                                translated_word, romanization, tags_json
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                entry_id,
                                translation.get("sense"),
                                translation.get("code") or translation.get("lang_code"),
                                str(translated).strip(),
                                translation.get("roman"),
                                json_text(translation.get("tags")),
                            ),
                        )

                inserted += 1
                if inserted % 5000 == 0:
                    connection.commit()
                    connection.execute("BEGIN")
                    print(f"Inserted {inserted:,} entries from {processed:,} records")
                if limit is not None and inserted >= limit:
                    break

        source_metadata = read_source_metadata(source_dir)
        insert_metadata(
            connection,
            {
                "schema_version": 1,
                "pack_id": pack["id"],
                "title": pack["title"],
                "source_language": source_language,
                "definition_language": definition_language,
                "source_type": "wiktionary",
                "source_url": source_metadata.get("url") or pack["source"].get("url"),
                "source_sha256": source_metadata.get("sha256"),
                "built_at": utc_now(),
            },
        )
        connection.commit()
        finalize_database(connection)
        counts = database_counts(connection)
    finally:
        connection.close()

    return {
        "database": db_path,
        "counts": counts,
        "source": read_source_metadata(source_dir),
    }
