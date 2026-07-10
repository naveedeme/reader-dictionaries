from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from build_freedict import build as build_freedict
from build_wiktionary import build as build_wiktionary
from build_wordnet import build as build_wordnet
from common import (
    REPO_ROOT,
    default_version,
    deterministic_zip,
    get_pack,
    load_config,
    sha256_file,
    utc_now,
    write_json,
)

BUILDERS = {
    "wiktionary": build_wiktionary,
    "freedict": build_freedict,
    "wordnet": build_wordnet,
}


def write_licensing(pack: dict[str, Any], stage: Path, result: dict[str, Any]) -> None:
    source_type = pack["source"]["type"]
    if source_type == "wiktionary":
        shutil.copy2(
            REPO_ROOT / "config/licenses/CC-BY-SA-4.0.txt",
            stage / "LICENSE.txt",
        )
        attribution = f"""# Attribution

**{pack['title']}** was generated from Wiktionary-derived structured data provided by Kaikki/Wiktextract.

- Source homepage: {pack['source'].get('homepage', pack['source'].get('url'))}
- Source language: {pack['source_language']}
- Definition language: {pack['definition_language']}
- Downloaded source: {result.get('source', {}).get('url', pack['source'].get('url'))}
- Builder: https://github.com/naveedeme/reader-dictionaries
- Built at: {utc_now()}

The dictionary text remains subject to the applicable Wiktionary/Wikimedia licence and attribution requirements. The included CC BY-SA 4.0 legal text must remain with redistributed copies.
"""
    elif source_type == "wordnet":
        attribution = f"""# Attribution

**{pack['title']}** is derived from Princeton WordNet 3.0.

- Project: https://wordnet.princeton.edu/
- Source archive: {pack['source'].get('url')}
- Builder: https://github.com/naveedeme/reader-dictionaries
- Built at: {utc_now()}

WordNet is provided under the licence included in `LICENSE.txt`. Preserve that file and cite WordNet when redistributing or using the pack.
"""
    elif source_type == "freedict":
        source_metadata = result.get("source", {})
        source_location = (
            source_metadata.get("url")
            or pack["source"].get("homepage")
            or pack["source"].get("repository")
            or "https://freedict.org/"
        )
        attribution = f"""# Attribution

**{pack['title']}** is derived from the FreeDict dictionary `{pack['source']['dictionary_id']}`.

- Project: https://freedict.org/
- Source location: {source_location}
- Source revision: {source_metadata.get('commit') or source_metadata.get('lastModified') or 'see source.json metadata in manifest'}
- Builder: https://github.com/naveedeme/reader-dictionaries
- Built at: {utc_now()}

FreeDict dictionaries have per-dictionary licences. Preserve the complete extracted legal text in `LICENSE.txt` with every redistributed copy.
"""
    else:
        raise ValueError(source_type)
    (stage / "ATTRIBUTION.md").write_text(attribution, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a compact offline dictionary package")
    parser.add_argument("--pack", required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", default=default_version())
    parser.add_argument("--limit", type=int)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()

    config = load_config(args.config)
    pack = get_pack(config, args.pack)
    source_type = pack["source"]["type"]
    builder = BUILDERS.get(source_type)
    if builder is None:
        raise ValueError(f"No builder for source type {source_type}")

    args.output.mkdir(parents=True, exist_ok=True)
    safe_version = args.version.replace("/", "-").replace(" ", "-")
    archive_name = f"{pack['id']}-{safe_version}.zip"
    archive_path = args.output / archive_name

    with tempfile.TemporaryDirectory(prefix=f"build-{pack['id']}-") as temporary:
        stage = Path(temporary)
        result = builder(pack, args.source.resolve(), stage, args.limit)
        write_licensing(pack, stage, result)
        database = stage / "dictionary.sqlite"
        counts = result["counts"]
        manifest = {
            "schemaVersion": int(config.get("schema_version", 1)),
            "id": pack["id"],
            "title": pack["title"],
            "description": pack.get("description", ""),
            "logicalId": pack.get("logical_id", pack["id"]),
            "shard": pack.get("shard"),
            "version": safe_version,
            "sourceType": source_type,
            "sourceLanguage": pack["source_language"],
            "definitionLanguage": pack["definition_language"],
            "license": pack.get("license", "See LICENSE.txt"),
            "licenseFile": "LICENSE.txt",
            "attributionFile": "ATTRIBUTION.md",
            "databaseFile": "dictionary.sqlite",
            "databaseSha256": sha256_file(database),
            "installedSize": sum(path.stat().st_size for path in stage.iterdir() if path.is_file()),
            "entryCount": counts["entries"],
            "senseCount": counts["senses"],
            "exampleCount": counts["examples"],
            "formCount": counts["forms"],
            "translationCount": counts["translations"],
            "relationCount": counts["relations"],
            "minimumAppSchemaVersion": 1,
            "archiveFile": archive_name,
            "builtAt": utc_now(),
            "source": result.get("source", {}),
        }
        write_json(stage / "manifest.json", manifest)
        deterministic_zip(stage, archive_path)

    checksum = sha256_file(archive_path)
    (args.output / f"{archive_name}.sha256").write_text(
        f"{checksum}  {archive_name}\n", encoding="utf-8"
    )
    print(json.dumps({"archive": str(archive_path), "sha256": checksum, "manifest": manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
