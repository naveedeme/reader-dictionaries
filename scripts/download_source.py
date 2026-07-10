from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from common import get_pack, load_config, sha256_file, utc_now, write_json

USER_AGENT = "reader-dictionaries/1.0 (+https://github.com/naveedeme/reader-dictionaries)"
CHUNK_SIZE = 1024 * 1024


def create_http_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    return session


def download_file(url: str, destination: Path) -> dict[str, Any]:
    """Download one file atomically and return reproducibility metadata."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    destination.unlink(missing_ok=True)

    try:
        with create_http_session() as session, session.get(
            url,
            stream=True,
            timeout=(30, 300),
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        handle.write(chunk)
            temporary.replace(destination)
            return {
                "url": response.url,
                "requestedUrl": url,
                "etag": response.headers.get("ETag"),
                "lastModified": response.headers.get("Last-Modified"),
                "contentType": response.headers.get("Content-Type"),
                "size": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "file": destination.name,
            }
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise


def download_http(urls: list[str], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for url in urls:
        name = Path(urlparse(url).path).name or "source.data"
        destination = output_dir / name
        try:
            file_metadata = download_file(url, destination)
            return {
                "kind": "http",
                "downloadedAt": utc_now(),
                **file_metadata,
            }
        except Exception as error:  # noqa: BLE001
            last_error = error
            print(f"Source download failed: {url}: {error}", file=sys.stderr)
    raise RuntimeError(f"All configured source URLs failed: {last_error}")


def freedict_generated_urls(source: dict[str, Any]) -> dict[str, str]:
    dictionary_id = str(source["dictionary_id"])
    base_url = str(
        source.get(
            "base_url",
            f"https://download.freedict.org/generated/{dictionary_id}",
        )
    ).rstrip("/")
    return {
        "tei": str(source.get("tei_url", f"{base_url}/{dictionary_id}.tei")),
        "license": str(source.get("license_url", f"{base_url}/COPYING")),
    }


def download_freedict_generated(source: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Download generated FreeDict TEI directly from the official service.

    Some large FreeDict dictionaries are generated and intentionally do not live in
    the fd-dictionaries Git repository. The official generated service exposes the
    TEI source and its COPYING file, which are sufficient for this builder.
    """
    dictionary_id = str(source["dictionary_id"])
    urls = freedict_generated_urls(source)
    output_dir.mkdir(parents=True, exist_ok=True)

    tei_metadata = download_file(urls["tei"], output_dir / f"{dictionary_id}.tei")
    try:
        license_metadata = download_file(urls["license"], output_dir / "COPYING")
    except Exception:
        # Do not leave an unlicensed source tree if the legal text failed to download.
        shutil.rmtree(output_dir, ignore_errors=True)
        raise

    return {
        "kind": "freedict-generated",
        "dictionaryId": dictionary_id,
        "downloadedAt": utc_now(),
        "url": tei_metadata["url"],
        "requestedUrl": tei_metadata["requestedUrl"],
        "size": tei_metadata["size"],
        "sha256": tei_metadata["sha256"],
        "lastModified": tei_metadata.get("lastModified"),
        "licenseUrl": license_metadata["url"],
        "licenseSha256": license_metadata["sha256"],
        "files": [tei_metadata, license_metadata],
    }


def download_freedict_git(source: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    repository = source.get("repository", "https://github.com/freedict/fd-dictionaries.git")
    ref = source.get("ref", "master")
    dictionary_id = str(source["dictionary_id"])
    checkout = output_dir / "checkout"
    if checkout.exists():
        shutil.rmtree(checkout)
    output_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--filter=blob:none",
            "--sparse",
            "--branch",
            str(ref),
            str(repository),
            str(checkout),
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "sparse-checkout", "set", dictionary_id],
        check=True,
    )
    source_dir = checkout / dictionary_id
    if not source_dir.exists():
        raise FileNotFoundError(
            f"FreeDict dictionary '{dictionary_id}' was not found in {repository}@{ref}. "
            "For generated dictionaries configure source.mode: generated."
        )
    final_dir = output_dir / dictionary_id
    shutil.copytree(source_dir, final_dir, dirs_exist_ok=True)
    commit = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    shutil.rmtree(checkout)
    return {
        "kind": "git",
        "repository": repository,
        "ref": ref,
        "commit": commit,
        "dictionaryId": dictionary_id,
        "downloadedAt": utc_now(),
    }


def download_freedict(source: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    mode = str(source.get("mode", "git")).casefold()
    if mode == "git":
        return download_freedict_git(source, output_dir)
    if mode == "generated":
        return download_freedict_generated(source, output_dir)
    raise ValueError(f"Unsupported FreeDict source mode: {mode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download a configured dictionary source")
    parser.add_argument("--pack", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()

    config = load_config(args.config)
    pack = get_pack(config, args.pack)
    source = pack["source"]
    output = args.output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    source_type = source["type"]
    if source_type in {"wiktionary", "wordnet", "http"}:
        urls = [source["url"], *source.get("fallback_urls", [])]
        metadata = download_http(urls, output)
    elif source_type == "freedict":
        metadata = download_freedict(source, output)
    else:
        raise ValueError(f"Unsupported source type: {source_type}")

    metadata["packId"] = pack["id"]
    metadata["sourceType"] = source_type
    write_json(output / "source.json", metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
