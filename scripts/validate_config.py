from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

from common import load_config

ALLOWED_SOURCE_TYPES = {"wiktionary", "freedict", "wordnet"}
ALLOWED_FREEDICT_MODES = {"git", "generated"}
PACK_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LANGUAGE_CODE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]+)*$")


def is_https_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate dictionary source configuration")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    seen: set[str] = set()
    errors: list[str] = []

    repository = config.get("repository")
    if not isinstance(repository, str) or "/" not in repository:
        errors.append("Top-level repository must be in owner/name form")
    if not is_https_url(config.get("catalog_url")):
        errors.append("Top-level catalog_url must be HTTPS")

    for pack in config["packs"]:
        pack_id = pack.get("id")
        if not pack_id:
            errors.append("A pack is missing id")
            continue
        if not isinstance(pack_id, str) or not PACK_ID.fullmatch(pack_id):
            errors.append(f"Invalid pack id: {pack_id!r}")
        if pack_id in seen:
            errors.append(f"Duplicate pack id: {pack_id}")
        seen.add(pack_id)

        for required in (
            "title",
            "description",
            "source_language",
            "definition_language",
            "source",
            "license",
        ):
            if required not in pack:
                errors.append(f"{pack_id}: missing {required}")

        for field in ("source_language", "definition_language"):
            value = pack.get(field)
            if not isinstance(value, str) or not LANGUAGE_CODE.fullmatch(value):
                errors.append(f"{pack_id}: invalid {field}: {value!r}")

        groups = pack.get("groups")
        if not isinstance(groups, list) or not groups or not all(isinstance(item, str) and item for item in groups):
            errors.append(f"{pack_id}: groups must be a non-empty string list")
        smoke_tests = pack.get("smoke_tests", [])
        if not isinstance(smoke_tests, list) or not all(isinstance(item, str) and item for item in smoke_tests):
            errors.append(f"{pack_id}: smoke_tests must be a string list")

        shard = pack.get("shard")
        headword_shard = pack.get("headword_shard")
        if shard is not None:
            if not isinstance(shard, dict) or not all(key in shard for key in ("index", "count", "label")):
                errors.append(f"{pack_id}: shard requires index, count and label")
            if not pack.get("logical_id"):
                errors.append(f"{pack_id}: sharded pack requires logical_id")
            if not isinstance(headword_shard, dict):
                errors.append(f"{pack_id}: sharded pack requires headword_shard")
            elif not headword_shard.get("other") and not headword_shard.get("initials"):
                errors.append(f"{pack_id}: headword_shard requires initials or other=true")

        source = pack.get("source")
        if not isinstance(source, dict):
            errors.append(f"{pack_id}: source must be an object")
            continue
        source_type = source.get("type")
        if source_type not in ALLOWED_SOURCE_TYPES:
            errors.append(f"{pack_id}: unsupported source type {source_type}")
            continue

        if source_type in {"wiktionary", "wordnet"}:
            if not is_https_url(source.get("url")):
                errors.append(f"{pack_id}: source.url must be HTTPS")
            for fallback in source.get("fallback_urls", []):
                if not is_https_url(fallback):
                    errors.append(f"{pack_id}: every fallback URL must be HTTPS")

        if source_type == "freedict":
            dictionary_id = source.get("dictionary_id")
            if not isinstance(dictionary_id, str) or not PACK_ID.fullmatch(dictionary_id):
                errors.append(f"{pack_id}: invalid FreeDict dictionary_id")
            mode = source.get("mode", "git")
            if mode not in ALLOWED_FREEDICT_MODES:
                errors.append(f"{pack_id}: unsupported FreeDict mode {mode!r}")
            elif mode == "git":
                if not is_https_url(source.get("repository")):
                    errors.append(f"{pack_id}: Git FreeDict source requires HTTPS repository")
                if not source.get("ref"):
                    errors.append(f"{pack_id}: Git FreeDict source requires ref")
            elif mode == "generated":
                if not is_https_url(source.get("base_url")) and not is_https_url(source.get("tei_url")):
                    errors.append(f"{pack_id}: generated FreeDict source requires HTTPS base_url or tei_url")

    if errors:
        raise SystemExit("Configuration errors:\n- " + "\n- ".join(errors))
    print(f"Validated {len(seen)} dictionary pack definitions")


if __name__ == "__main__":
    main()
