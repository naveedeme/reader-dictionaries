from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from common import normalize_word, secure_extract_zip


def open_pack(path: Path, temporary: Path) -> tuple[Path, dict[str, Any]]:
    if path.is_dir():
        root = path
    elif zipfile.is_zipfile(path):
        root = temporary / "pack"
        root.mkdir(parents=True)
        secure_extract_zip(path, root)
    else:
        raise ValueError("Pack must be an extracted directory or dictionary ZIP")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return root / manifest["databaseFile"], manifest


def query(connection: sqlite3.Connection, word: str, language: str, limit: int) -> list[dict[str, Any]]:
    normalized = normalize_word(word, language)
    rows = connection.execute(
        """
        SELECT DISTINCT e.id, e.headword, e.part_of_speech, e.pronunciation, e.etymology
        FROM entries e
        LEFT JOIN forms f ON f.entry_id = e.id
        WHERE e.normalized_headword = ? OR f.normalized_form = ?
        ORDER BY CASE WHEN e.normalized_headword = ? THEN 0 ELSE 1 END,
                 e.headword, e.part_of_speech
        LIMIT ?
        """,
        (normalized, normalized, normalized, limit),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        entry_id = int(row[0])
        senses = [
            {"order": item[0], "definition": item[1]}
            for item in connection.execute(
                "SELECT sense_order, definition FROM senses WHERE entry_id=? ORDER BY sense_order",
                (entry_id,),
            )
        ]
        relations = [
            {"type": item[0], "word": item[1]}
            for item in connection.execute(
                "SELECT relation_type, related_word FROM relations WHERE entry_id=? ORDER BY relation_type, related_word LIMIT 100",
                (entry_id,),
            )
        ]
        result.append(
            {
                "id": entry_id,
                "headword": row[1],
                "partOfSpeech": row[2],
                "pronunciation": row[3],
                "etymology": row[4],
                "senses": senses,
                "relations": relations,
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Query a built offline dictionary package")
    parser.add_argument("pack", type=Path)
    parser.add_argument("word")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="query-dictionary-") as temp:
        database, manifest = open_pack(args.pack.resolve(), Path(temp))
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            results = query(
                connection,
                args.word,
                str(manifest["sourceLanguage"]),
                max(1, args.limit),
            )
        finally:
            connection.close()
    print(json.dumps({"pack": manifest["id"], "word": args.word, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
