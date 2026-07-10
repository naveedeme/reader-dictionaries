from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from common import (
    create_database,
    database_counts,
    finalize_database,
    insert_metadata,
    json_text,
    local_name,
    normalize_word,
    read_source_metadata,
    text_content,
    utc_now,
)


def descendants(element: ET.Element, name: str) -> list[ET.Element]:
    return [node for node in element.iter() if local_name(node.tag) == name]


def first_text(element: ET.Element, name: str) -> str | None:
    for node in element.iter():
        if local_name(node.tag) == name:
            value = text_content(node)
            if value:
                return value
    return None


def find_tei(source_dir: Path) -> Path:
    candidates = sorted(source_dir.rglob("*.tei")) + sorted(source_dir.rglob("*.xml"))
    if not candidates:
        raise FileNotFoundError(f"No FreeDict TEI/XML file found under {source_dir}")
    return candidates[0]


def extract_header(tei_path: Path) -> tuple[str, str | None]:
    availability = ""
    edition = None
    for event, element in ET.iterparse(tei_path, events=("end",)):
        name = local_name(element.tag)
        if name == "edition" and edition is None:
            edition = text_content(element) or None
        if name == "availability" and not availability:
            availability = text_content(element)
        if name == "teiHeader":
            element.clear()
            break
    return availability, edition


def direct_or_nested_quotes(sense: ET.Element, citation_type: str) -> list[str]:
    values: list[str] = []
    for citation in descendants(sense, "cit"):
        if citation.attrib.get("type", "").casefold() != citation_type.casefold():
            continue
        for quote in descendants(citation, "quote"):
            value = text_content(quote)
            if value:
                values.append(value)
    return values


def build(pack: dict[str, Any], source_dir: Path, stage_dir: Path, limit: int | None = None) -> dict[str, Any]:
    tei_path = find_tei(source_dir)
    availability, edition = extract_header(tei_path)
    licence_candidates = (
        sorted(source_dir.rglob("COPYING"))
        + sorted(source_dir.rglob("LICENSE"))
        + sorted(source_dir.rglob("LICENSE.txt"))
    )
    if licence_candidates:
        licence_text = licence_candidates[0].read_text(encoding="utf-8", errors="replace").strip()
        if availability and availability.casefold() not in licence_text.casefold():
            licence_text += f"\n\nTEI availability statement:\n{availability}"
    else:
        licence_text = availability or (
            "Licence information was not explicit in the TEI availability header. "
            "Do not publish this pack until its FreeDict licence has been verified."
        )
    (stage_dir / "LICENSE.txt").write_text(licence_text + "\n", encoding="utf-8")

    source_language = pack["source_language"]
    definition_language = pack["definition_language"]
    db_path = stage_dir / "dictionary.sqlite"
    connection = create_database(db_path)
    inserted = 0

    try:
        connection.execute("BEGIN")
        context = ET.iterparse(tei_path, events=("start", "end"))
        _, root = next(context)
        for event, entry in context:
            if event != "end" or local_name(entry.tag) != "entry":
                continue

            lemma_forms: list[str] = []
            all_forms: list[tuple[str, str | None]] = []
            for form in descendants(entry, "form"):
                form_type = form.attrib.get("type")
                for orth in descendants(form, "orth"):
                    value = text_content(orth)
                    if not value:
                        continue
                    all_forms.append((value, form_type))
                    if form_type == "lemma":
                        lemma_forms.append(value)
            if not lemma_forms:
                orths = [text_content(node) for node in descendants(entry, "orth")]
                lemma_forms = [value for value in orths if value][:1]
            if not lemma_forms:
                entry.clear()
                root.clear()
                continue

            headword = lemma_forms[0]
            part_of_speech = first_text(entry, "pos")
            pronunciation = first_text(entry, "pron")

            sense_payloads: list[tuple[str, list[str], list[str]]] = []
            for sense in descendants(entry, "sense"):
                definitions = [text_content(node) for node in descendants(sense, "def")]
                definitions = [value for value in definitions if value]
                translations = direct_or_nested_quotes(sense, "trans")
                examples = direct_or_nested_quotes(sense, "example")
                if definitions:
                    definition = " — ".join(dict.fromkeys(definitions))
                elif translations:
                    definition = "; ".join(dict.fromkeys(translations))
                else:
                    continue
                sense_payloads.append((definition, translations, examples))
            if not sense_payloads:
                entry.clear()
                root.clear()
                continue

            cursor = connection.execute(
                """
                INSERT INTO entries(
                    headword, normalized_headword, language_code,
                    definition_language_code, part_of_speech, pronunciation,
                    source_entry_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    headword,
                    normalize_word(headword, source_language),
                    source_language,
                    definition_language,
                    part_of_speech,
                    pronunciation,
                    entry.attrib.get("{http://www.w3.org/XML/1998/namespace}id") or entry.attrib.get("id"),
                ),
            )
            entry_id = int(cursor.lastrowid)

            for order, (definition, translations, examples) in enumerate(sense_payloads, start=1):
                sense_cursor = connection.execute(
                    "INSERT INTO senses(entry_id, sense_order, definition) VALUES (?, ?, ?)",
                    (entry_id, order, definition),
                )
                sense_id = int(sense_cursor.lastrowid)
                for example in examples:
                    connection.execute(
                        "INSERT INTO examples(sense_id, example_text) VALUES (?, ?)",
                        (sense_id, example),
                    )
                for translated in translations:
                    connection.execute(
                        """
                        INSERT INTO translations(
                            entry_id, target_language_code, translated_word
                        ) VALUES (?, ?, ?)
                        """,
                        (entry_id, definition_language, translated),
                    )

            seen_forms: set[str] = {headword}
            for value, form_type in all_forms:
                if value in seen_forms:
                    continue
                seen_forms.add(value)
                connection.execute(
                    """
                    INSERT INTO forms(entry_id, form, normalized_form, tags_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        entry_id,
                        value,
                        normalize_word(value, source_language),
                        json_text([form_type] if form_type else None),
                    ),
                )

            inserted += 1
            entry.clear()
            root.clear()
            if inserted % 5000 == 0:
                connection.commit()
                connection.execute("BEGIN")
                print(f"Inserted {inserted:,} FreeDict entries")
            if limit is not None and inserted >= limit:
                break

        metadata = read_source_metadata(source_dir)
        insert_metadata(
            connection,
            {
                "schema_version": 1,
                "pack_id": pack["id"],
                "title": pack["title"],
                "source_language": source_language,
                "definition_language": definition_language,
                "source_type": "freedict",
                "source_repository": metadata.get("repository"),
                "source_url": metadata.get("url"),
                "source_commit": metadata.get("commit"),
                "source_sha256": metadata.get("sha256"),
                "source_edition": edition,
                "built_at": utc_now(),
            },
        )
        connection.commit()
        finalize_database(connection)
        counts = database_counts(connection)
    finally:
        connection.close()

    return {"database": db_path, "counts": counts, "source": read_source_metadata(source_dir)}
