from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common import normalize_word  # noqa: E402


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def test_language_normalization() -> None:
    assert normalize_word("  BOOKS  ", "en") == "books"
    assert normalize_word("كِتاب", "fa") == "کتاب"
    assert normalize_word("أَلْكِتَاب", "ar") == "الكتاب"


@pytest.mark.parametrize(
    ("pack", "source"),
    [
        ("fixture-wiktionary", "tests/fixtures/wiktionary"),
        ("fixture-freedict", "tests/fixtures/freedict"),
        ("fixture-wordnet", "tests/fixtures/wordnet"),
    ],
)
def test_build_and_validate_fixture(tmp_path: Path, pack: str, source: str) -> None:
    output = tmp_path / "dist"
    run(
        "scripts/build_pack.py",
        "--config",
        "tests/fixtures/dictionaries.test.yml",
        "--pack",
        pack,
        "--source",
        source,
        "--output",
        str(output),
        "--version",
        "test",
    )
    archive = output / f"{pack}-test.zip"
    assert archive.exists()
    run(
        "scripts/validate_pack.py",
        str(archive),
        "--config",
        "tests/fixtures/dictionaries.test.yml",
    )


def test_freedict_generated_urls() -> None:
    from download_source import freedict_generated_urls

    urls = freedict_generated_urls(
        {
            "dictionary_id": "eng-deu",
            "base_url": "https://download.freedict.org/generated/eng-deu/",
        }
    )
    assert urls == {
        "tei": "https://download.freedict.org/generated/eng-deu/eng-deu.tei",
        "license": "https://download.freedict.org/generated/eng-deu/COPYING",
    }


def test_catalog_merges_previous_packs(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    run(
        "scripts/build_pack.py",
        "--config",
        "tests/fixtures/dictionaries.test.yml",
        "--pack",
        "fixture-wiktionary",
        "--source",
        "tests/fixtures/wiktionary",
        "--output",
        str(output),
        "--version",
        "new",
    )
    previous = tmp_path / "previous.json"
    previous.write_text(
        json.dumps(
            {
                "catalogVersion": 1,
                "packs": [
                    {
                        "id": "previous-pack",
                        "title": "Previous Pack",
                        "description": "Preserved entry",
                        "version": "old",
                        "sourceType": "wiktionary",
                        "sourceLanguage": "fr",
                        "definitionLanguage": "en",
                        "license": "CC-BY-SA-4.0",
                        "schemaVersion": 1,
                        "minimumAppSchemaVersion": 1,
                        "entryCount": 1,
                        "senseCount": 1,
                        "exampleCount": 0,
                        "formCount": 0,
                        "translationCount": 0,
                        "relationCount": 0,
                        "downloadSize": 100,
                        "installedSize": 200,
                        "sha256": "0" * 64,
                        "assetName": "previous.zip",
                        "downloadUrl": "https://example.invalid/previous.zip",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    catalog = tmp_path / "catalog.json"
    run(
        "scripts/build_catalog.py",
        "--packs",
        str(output),
        "--output",
        str(catalog),
        "--repository",
        "naveedeme/reader-dictionaries",
        "--release-tag",
        "dictionaries-test",
        "--previous-catalog",
        str(previous),
    )
    result = json.loads(catalog.read_text(encoding="utf-8"))
    assert {item["id"] for item in result["packs"]} == {
        "previous-pack",
        "fixture-wiktionary",
    }
    assert result["updatedPackIds"] == ["fixture-wiktionary"]


def test_wiktionary_headword_shards() -> None:
    from build_wiktionary import headword_allowed

    assert headword_allowed({"headword_shard": {"initials": "abcd"}}, "book")
    assert not headword_allowed({"headword_shard": {"initials": "abcd"}}, "water")
    assert headword_allowed({"headword_shard": {"other": True}}, "éclair")
    assert not headword_allowed({"headword_shard": {"other": True}}, "book")


def test_generated_freedict_downloader_writes_tei_and_license(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import download_source

    def fake_download(url: str, destination: Path) -> dict:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("sample", encoding="utf-8")
        return {
            "url": url,
            "requestedUrl": url,
            "size": destination.stat().st_size,
            "sha256": "a" * 64,
            "file": destination.name,
            "lastModified": "test",
        }

    monkeypatch.setattr(download_source, "download_file", fake_download)
    metadata = download_source.download_freedict_generated(
        {
            "dictionary_id": "eng-spa",
            "base_url": "https://download.freedict.org/generated/eng-spa",
        },
        tmp_path,
    )
    assert (tmp_path / "eng-spa.tei").read_text(encoding="utf-8") == "sample"
    assert (tmp_path / "COPYING").read_text(encoding="utf-8") == "sample"
    assert metadata["kind"] == "freedict-generated"
    assert metadata["dictionaryId"] == "eng-spa"


def test_secure_zip_rejects_path_traversal(tmp_path: Path) -> None:
    import zipfile
    from common import secure_extract_zip

    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", "bad")
    with pytest.raises(ValueError, match="Unsafe ZIP member"):
        secure_extract_zip(archive, tmp_path / "extract")
    assert not (tmp_path / "outside.txt").exists()
