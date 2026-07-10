from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from common import get_pack, load_config, normalize_word, secure_extract_zip, sha256_file

MAX_GITHUB_RELEASE_ASSET_BYTES = 2 * 1024 * 1024 * 1024 - 1

REQUIRED_TABLES = {
    "metadata",
    "entries",
    "senses",
    "examples",
    "forms",
    "translations",
    "relations",
    "entries_fts",
}


def validate(
    archive: Path,
    config_path: Path | None = None,
    max_archive_bytes: int = MAX_GITHUB_RELEASE_ASSET_BYTES,
) -> dict:
    if not archive.exists() or not archive.is_file():
        raise FileNotFoundError(archive)
    if archive.stat().st_size > max_archive_bytes:
        raise ValueError(
            f"Archive is too large for a GitHub Release asset: "
            f"{archive.stat().st_size:,} > {max_archive_bytes:,} bytes"
        )
    with tempfile.TemporaryDirectory(prefix="validate-dictionary-") as temporary:
        root = Path(temporary)
        secure_extract_zip(archive, root)
        required_files = ["manifest.json", "dictionary.sqlite", "LICENSE.txt", "ATTRIBUTION.md"]
        for name in required_files:
            path = root / name
            if not path.exists() or path.stat().st_size == 0:
                raise ValueError(f"Required package file is missing or empty: {name}")

        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        required_manifest = {
            "schemaVersion", "id", "title", "version", "sourceType",
            "sourceLanguage", "definitionLanguage", "license",
            "databaseFile", "databaseSha256", "entryCount",
            "minimumAppSchemaVersion",
        }
        missing_manifest = required_manifest - set(manifest)
        if missing_manifest:
            raise ValueError(f"Manifest fields missing: {sorted(missing_manifest)}")
        if manifest["databaseFile"] != "dictionary.sqlite":
            raise ValueError("Unsupported database file name")
        if manifest.get("licenseFile") != "LICENSE.txt" or manifest.get("attributionFile") != "ATTRIBUTION.md":
            raise ValueError("Manifest licence/attribution file names are invalid")
        database = root / manifest["databaseFile"]
        actual_db_hash = sha256_file(database)
        if actual_db_hash != manifest["databaseSha256"]:
            raise ValueError("Database SHA-256 does not match manifest")

        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"SQLite integrity check failed: {integrity}")
            user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if user_version != int(manifest["schemaVersion"]):
                raise ValueError(f"Schema mismatch: database={user_version}, manifest={manifest['schemaVersion']}")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
            missing = REQUIRED_TABLES - tables
            if missing:
                raise ValueError(f"Missing database tables: {sorted(missing)}")
            actual_entries = int(connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
            if actual_entries != int(manifest["entryCount"]):
                raise ValueError("Entry count does not match manifest")
            if actual_entries <= 0:
                raise ValueError("Dictionary contains no entries")
            fts_rows = int(connection.execute("SELECT COUNT(*) FROM entries_fts").fetchone()[0])
            if fts_rows != actual_entries:
                raise ValueError("FTS index row count does not match entries")

            if config_path:
                config = load_config(config_path)
                pack = get_pack(config, manifest["id"])
                for word in pack.get("smoke_tests", []):
                    normalized = normalize_word(word, pack["source_language"])
                    count = int(
                        connection.execute(
                            """
                            SELECT COUNT(*) FROM entries WHERE normalized_headword = ?
                            """,
                            (normalized,),
                        ).fetchone()[0]
                    )
                    if count == 0:
                        raise ValueError(f"Smoke-test headword not found: {word}")
        finally:
            connection.close()

        return {
            "archive": str(archive),
            "archiveSha256": sha256_file(archive),
            "id": manifest["id"],
            "version": manifest["version"],
            "entryCount": manifest["entryCount"],
            "valid": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an offline dictionary ZIP")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--max-archive-bytes",
        type=int,
        default=MAX_GITHUB_RELEASE_ASSET_BYTES,
    )
    args = parser.parse_args()
    print(json.dumps(validate(args.archive, args.config, args.max_archive_bytes), indent=2))


if __name__ == "__main__":
    main()
