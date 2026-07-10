from __future__ import annotations

import argparse
import html
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from common import load_config, sha256_file, utc_now, write_json


def read_manifest(archive: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as bundle:
        try:
            return json.loads(bundle.read("manifest.json").decode("utf-8"))
        except KeyError as error:
            raise ValueError(f"{archive} does not contain manifest.json") from error


def read_previous_catalog(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists() or path.stat().st_size == 0:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    packs = data.get("packs", [])
    if not isinstance(packs, list):
        raise ValueError("Previous catalog has no packs array")
    return [item for item in packs if isinstance(item, dict) and item.get("id")]


def make_index(catalog: dict[str, Any]) -> str:
    cards = []
    for pack in catalog["packs"]:
        cards.append(
            f"""
            <article>
              <h2>{html.escape(pack['title'])}</h2>
              <p>{html.escape(pack.get('description', ''))}</p>
              <dl>
                <dt>Languages</dt><dd>{html.escape(pack['sourceLanguage'])} → {html.escape(pack['definitionLanguage'])}</dd>
                <dt>Version</dt><dd>{html.escape(pack['version'])}</dd>
                <dt>Entries</dt><dd>{pack['entryCount']:,}</dd>
                <dt>Download</dt><dd>{pack['downloadSize'] / 1024 / 1024:.1f} MB</dd>
                <dt>Licence</dt><dd>{html.escape(pack['license'])}</dd>
              </dl>
              <a href="{html.escape(pack['downloadUrl'])}">Download pack</a>
            </article>
            """
        )
    body = "\n".join(cards) or "<p>No dictionary packs have been published yet.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Reader Offline Dictionaries</title>
  <style>
    body{{font-family:system-ui,sans-serif;max-width:1100px;margin:auto;padding:2rem;line-height:1.5}}
    main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}}
    article{{border:1px solid #bbb;border-radius:12px;padding:1rem}}
    dl{{display:grid;grid-template-columns:auto 1fr;gap:.25rem .75rem}}dt{{font-weight:700}}
  </style>
</head>
<body>
  <h1>Reader Offline Dictionaries</h1>
  <p>Machine-readable catalog: <a href="catalog.json">catalog.json</a></p>
  <main>{body}</main>
</body>
</html>
"""


def catalog_entry(archive: Path, manifest: dict[str, Any], repository: str, release_tag: str) -> dict[str, Any]:
    asset_name = archive.name
    return {
        "id": manifest["id"],
        "title": manifest["title"],
        "description": manifest.get("description", ""),
        "logicalId": manifest.get("logicalId", manifest["id"]),
        "shard": manifest.get("shard"),
        "version": manifest["version"],
        "sourceType": manifest["sourceType"],
        "sourceLanguage": manifest["sourceLanguage"],
        "definitionLanguage": manifest["definitionLanguage"],
        "license": manifest["license"],
        "schemaVersion": manifest["schemaVersion"],
        "minimumAppSchemaVersion": manifest.get("minimumAppSchemaVersion", 1),
        "entryCount": manifest["entryCount"],
        "senseCount": manifest["senseCount"],
        "exampleCount": manifest.get("exampleCount", 0),
        "formCount": manifest["formCount"],
        "translationCount": manifest.get("translationCount", 0),
        "relationCount": manifest["relationCount"],
        "downloadSize": archive.stat().st_size,
        "installedSize": manifest["installedSize"],
        "sha256": sha256_file(archive),
        "assetName": asset_name,
        "downloadUrl": (
            f"https://github.com/{repository}/releases/download/"
            f"{release_tag}/{asset_name}"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Android dictionary catalog")
    parser.add_argument("--packs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--previous-catalog", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--pages-dir", type=Path)
    args = parser.parse_args()

    # Start with the existing catalog so publishing one pack updates that pack instead
    # of making every other installed dictionary disappear from the app's store.
    merged: dict[str, dict[str, Any]] = {
        item["id"]: item for item in read_previous_catalog(args.previous_catalog)
    }

    if args.config:
        config = load_config(args.config)
        enabled_ids = {
            pack["id"] for pack in config["packs"] if pack.get("enabled", True)
        }
        merged = {pack_id: item for pack_id, item in merged.items() if pack_id in enabled_ids}

    built_ids: list[str] = []
    for archive in sorted(args.packs.rglob("*.zip")):
        manifest = read_manifest(archive)
        entry = catalog_entry(archive, manifest, args.repository, args.release_tag)
        merged[entry["id"]] = entry
        built_ids.append(entry["id"])

    if not built_ids:
        raise ValueError(f"No dictionary ZIP files found under {args.packs}")

    entries = sorted(
        merged.values(),
        key=lambda item: (
            item["sourceLanguage"],
            item["definitionLanguage"],
            item["title"],
        ),
    )
    catalog = {
        "catalogVersion": 1,
        "generatedAt": utc_now(),
        "repository": args.repository,
        "latestReleaseTag": args.release_tag,
        "latestCatalogUrl": f"https://github.com/{args.repository}/releases/latest/download/catalog.json",
        "updatedPackIds": sorted(built_ids),
        "packs": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, catalog)

    if args.pages_dir:
        args.pages_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.output, args.pages_dir / "catalog.json")
        (args.pages_dir / "index.html").write_text(make_index(catalog), encoding="utf-8")
        (args.pages_dir / ".nojekyll").write_text("", encoding="utf-8")

    print(
        json.dumps(
            {
                "packs": len(entries),
                "updated": sorted(built_ids),
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
