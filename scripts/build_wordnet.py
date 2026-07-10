from __future__ import annotations

from pathlib import Path
from typing import Any

from common import (
    REPO_ROOT,
    create_database,
    database_counts,
    finalize_database,
    insert_metadata,
    normalize_word,
    read_source_metadata,
    secure_extract_tar,
    split_gloss,
    utc_now,
)

POS_FILES = {
    "noun": ("n", "noun"),
    "verb": ("v", "verb"),
    "adj": ("a", "adjective"),
    "adv": ("r", "adverb"),
}

POINTER_TYPES = {
    "!": "antonym",
    "@": "hypernym",
    "@i": "instance_hypernym",
    "~": "hyponym",
    "~i": "instance_hyponym",
    "#m": "member_holonym",
    "#s": "substance_holonym",
    "#p": "part_holonym",
    "%m": "member_meronym",
    "%s": "substance_meronym",
    "%p": "part_meronym",
    "*": "entailment",
    ">": "cause",
    "^": "also_see",
    "$": "verb_group",
    "&": "similar",
    "<": "participle",
    "\\": "pertainym",
    "+": "derivationally_related",
}


def normalize_pos_code(code: str) -> str:
    # WordNet adjective satellites use `s`; their data lives in data.adj and
    # pointer targets may use either `a` or `s`. Treat both as the same index.
    return "a" if code == "s" else code


def find_wordnet_dict(source_dir: Path) -> Path:
    archives = list(source_dir.glob("*.tar.gz")) + list(source_dir.glob("*.tgz"))
    if archives:
        extracted = source_dir / "extracted"
        if not extracted.exists():
            extracted.mkdir()
            secure_extract_tar(archives[0], extracted)
    for data_noun in source_dir.rglob("data.noun"):
        return data_noun.parent
    raise FileNotFoundError(f"Could not find WordNet dict/data.noun under {source_dir}")


def parse_synsets(dict_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    synsets: dict[tuple[str, str], dict[str, Any]] = {}
    for filename, (_pos_code, pos_name) in POS_FILES.items():
        path = dict_dir / f"data.{filename}"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line or line.startswith("  ") or " | " not in line:
                    continue
                data, gloss = line.rstrip("\n").split(" | ", 1)
                fields = data.split()
                if len(fields) < 5:
                    continue
                offset = fields[0]
                actual_pos_code = normalize_pos_code(fields[2])
                word_count = int(fields[3], 16)
                index = 4
                words: list[str] = []
                for _ in range(word_count):
                    words.append(fields[index].replace("_", " "))
                    index += 2
                pointer_count = int(fields[index])
                index += 1
                pointers: list[tuple[str, str, str]] = []
                for _ in range(pointer_count):
                    symbol = fields[index]
                    target_offset = fields[index + 1]
                    target_pos = normalize_pos_code(fields[index + 2])
                    pointers.append((symbol, target_offset, target_pos))
                    index += 4
                definition, examples = split_gloss(gloss)
                synsets[(actual_pos_code, offset)] = {
                    "pos_code": actual_pos_code,
                    "pos_name": pos_name,
                    "offset": offset,
                    "words": words,
                    "definition": definition,
                    "examples": examples,
                    "pointers": pointers,
                }
    return synsets


def build(pack: dict[str, Any], source_dir: Path, stage_dir: Path, limit: int | None = None) -> dict[str, Any]:
    dict_dir = find_wordnet_dict(source_dir)
    synsets = parse_synsets(dict_dir)
    db_path = stage_dir / "dictionary.sqlite"
    connection = create_database(db_path)
    lemma_entries: dict[str, list[int]] = {}
    inserted = 0

    try:
        connection.execute("BEGIN")
        for synset in synsets.values():
            for word in synset["words"]:
                cursor = connection.execute(
                    """
                    INSERT INTO entries(
                        headword, normalized_headword, language_code,
                        definition_language_code, part_of_speech, source_entry_id
                    ) VALUES (?, ?, 'en', 'en', ?, ?)
                    """,
                    (
                        word,
                        normalize_word(word, "en"),
                        synset["pos_name"],
                        f"{synset['pos_code']}:{synset['offset']}",
                    ),
                )
                entry_id = int(cursor.lastrowid)
                lemma_entries.setdefault(normalize_word(word, "en"), []).append(entry_id)
                sense_cursor = connection.execute(
                    "INSERT INTO senses(entry_id, sense_order, definition) VALUES (?, 1, ?)",
                    (entry_id, synset["definition"]),
                )
                sense_id = int(sense_cursor.lastrowid)
                for example in synset["examples"]:
                    connection.execute(
                        "INSERT INTO examples(sense_id, example_text) VALUES (?, ?)",
                        (sense_id, example),
                    )
                for synonym in synset["words"]:
                    if synonym != word:
                        connection.execute(
                            """
                            INSERT INTO relations(entry_id, relation_type, related_word, normalized_related_word)
                            VALUES (?, 'synonym', ?, ?)
                            """,
                            (entry_id, synonym, normalize_word(synonym, "en")),
                        )
                for symbol, target_offset, target_pos in synset["pointers"]:
                    target = synsets.get((target_pos, target_offset))
                    if not target:
                        continue
                    relation_type = POINTER_TYPES.get(symbol, f"wordnet_{symbol}")
                    for related in target["words"]:
                        connection.execute(
                            """
                            INSERT INTO relations(entry_id, relation_type, related_word, normalized_related_word)
                            VALUES (?, ?, ?, ?)
                            """,
                            (entry_id, relation_type, related, normalize_word(related, "en")),
                        )
                inserted += 1
                if inserted % 5000 == 0:
                    connection.commit()
                    connection.execute("BEGIN")
                    print(f"Inserted {inserted:,} WordNet entries")
                if limit is not None and inserted >= limit:
                    break
            if limit is not None and inserted >= limit:
                break

        for filename in POS_FILES:
            exception_file = dict_dir / f"{filename}.exc"
            if not exception_file.exists():
                continue
            with exception_file.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    values = [value.replace("_", " ") for value in line.split()]
                    if len(values) < 2:
                        continue
                    inflected, lemmas = values[0], values[1:]
                    for lemma in lemmas:
                        for entry_id in lemma_entries.get(normalize_word(lemma, "en"), []):
                            connection.execute(
                                """
                                INSERT INTO forms(entry_id, form, normalized_form, tags_json)
                                VALUES (?, ?, ?, '["inflected"]')
                                """,
                                (entry_id, inflected, normalize_word(inflected, "en")),
                            )

        source_metadata = read_source_metadata(source_dir)
        insert_metadata(
            connection,
            {
                "schema_version": 1,
                "pack_id": pack["id"],
                "title": pack["title"],
                "source_language": "en",
                "definition_language": "en",
                "source_type": "wordnet",
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

    licence_candidates = list(source_dir.rglob("LICENSE")) + list(source_dir.rglob("COPYING"))
    licence_source = licence_candidates[0] if licence_candidates else REPO_ROOT / "config/licenses/WORDNET-3.0.txt"
    (stage_dir / "LICENSE.txt").write_text(licence_source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

    return {"database": db_path, "counts": counts, "source": read_source_metadata(source_dir)}
