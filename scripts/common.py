from __future__ import annotations

import gzip
import hashlib
import json
import lzma
import re
import shutil
import stat
import sqlite3
import tarfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config" / "dictionaries.yml"
SCHEMA_PATH = REPO_ROOT / "schema" / "dictionary.sql"
SCHEMA_VERSION = 1

ARABIC_DIACRITICS = re.compile(
    "[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]"
)
WHITESPACE = re.compile(r"\s+")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_version() -> str:
    return datetime.now(timezone.utc).strftime("%Y.%m.%d")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("packs"), list):
        raise ValueError(f"Invalid dictionary configuration: {config_path}")
    return data


def get_pack(config: dict[str, Any], pack_id: str) -> dict[str, Any]:
    for pack in config["packs"]:
        if pack.get("id") == pack_id:
            return pack
    raise KeyError(f"Unknown dictionary pack: {pack_id}")


def normalize_word(value: str, language: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = WHITESPACE.sub(" ", text.strip()).casefold()

    if language in {"ar", "fa", "ur"}:
        text = ARABIC_DIACRITICS.sub("", text)
        text = text.replace("ـ", "")

    if language == "ar":
        text = (
            text.replace("أ", "ا")
            .replace("إ", "ا")
            .replace("آ", "ا")
            .replace("ٱ", "ا")
            .replace("ى", "ي")
        )
    elif language == "fa":
        text = text.replace("ك", "ک").replace("ي", "ی").replace("ى", "ی")
    elif language == "ur":
        text = text.replace("ك", "ک").replace("ي", "ی").replace("ى", "ی")

    return text


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def json_text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def text_content(element: Any) -> str:
    return WHITESPACE.sub(" ", "".join(element.itertext()).strip())


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find_source_file(source_dir: str | Path) -> Path:
    root = Path(source_dir)
    candidates = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "source.json"
        and not path.name.startswith(".")
    ]
    if not candidates:
        raise FileNotFoundError(f"No source file found under {root}")
    candidates.sort(key=lambda p: (p.suffix not in {".jsonl", ".gz", ".tei", ".xml"}, len(str(p))))
    return candidates[0]


def open_text_auto(path: str | Path):
    source = Path(path)
    suffixes = source.suffixes
    if suffixes and suffixes[-1] == ".gz":
        return gzip.open(source, "rt", encoding="utf-8", errors="replace")
    if suffixes and suffixes[-1] in {".xz", ".lzma"}:
        return lzma.open(source, "rt", encoding="utf-8", errors="replace")
    return source.open("r", encoding="utf-8", errors="replace")


def create_database(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("PRAGMA cache_size=-131072")
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return connection


def insert_metadata(connection: sqlite3.Connection, values: dict[str, Any]) -> None:
    connection.executemany(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
        [(str(key), str(value)) for key, value in values.items() if value is not None],
    )


def finalize_database(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM entries_fts")
    connection.execute(
        """
        INSERT INTO entries_fts(
            rowid,
            headword,
            normalized_headword,
            definitions,
            forms,
            relations
        )
        SELECT
            e.id,
            e.headword,
            e.normalized_headword,
            COALESCE((
                SELECT group_concat(s.definition, ' | ')
                FROM senses s
                WHERE s.entry_id = e.id
            ), ''),
            COALESCE((
                SELECT group_concat(f.form, ' | ')
                FROM forms f
                WHERE f.entry_id = e.id
            ), ''),
            COALESCE((
                SELECT group_concat(r.related_word, ' | ')
                FROM relations r
                WHERE r.entry_id = e.id
            ), '')
        FROM entries e
        """
    )
    connection.execute("ANALYZE")
    connection.execute("PRAGMA optimize")
    connection.commit()


def database_counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = ["entries", "senses", "examples", "forms", "translations", "relations"]
    return {
        name: int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
        for name in names
    }


def write_json(path: str | Path, value: Any) -> None:
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def read_source_metadata(source_dir: str | Path) -> dict[str, Any]:
    path = Path(source_dir) / "source.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def secure_extract_zip(archive: str | Path, destination: str | Path) -> None:
    destination_path = Path(destination).resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination_path / member.filename).resolve()
            unix_mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(unix_mode):
                raise ValueError(f"ZIP symbolic links are not allowed: {member.filename}")
            if destination_path != target and destination_path not in target.parents:
                raise ValueError(f"Unsafe ZIP member: {member.filename}")
        bundle.extractall(destination_path)


def secure_extract_tar(archive: str | Path, destination: str | Path) -> None:
    destination_path = Path(destination).resolve()
    with tarfile.open(archive, "r:*") as bundle:
        for member in bundle.getmembers():
            target = (destination_path / member.name).resolve()
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"TAR links/devices are not allowed: {member.name}")
            if destination_path != target and destination_path not in target.parents:
                raise ValueError(f"Unsafe TAR member: {member.name}")
        bundle.extractall(destination_path, filter="data")


def deterministic_zip(source_dir: str | Path, output_file: str | Path) -> None:
    source = Path(source_dir)
    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    fixed_time = (2026, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), fixed_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def copy_file(source: str | Path, destination: str | Path) -> None:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def split_gloss(gloss: str) -> tuple[str, list[str]]:
    examples = re.findall(r'"([^"]+)"', gloss)
    definition = re.sub(r';?\s*"[^"]+"', "", gloss).strip(" ;")
    return definition or gloss.strip(), examples
