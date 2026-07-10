# Reader Offline Dictionary Builder

A complete GitHub Actions pipeline that downloads open dictionary sources, converts them into compact indexed SQLite databases, validates them, publishes versioned ZIP packages in GitHub Releases, and generates the catalog consumed by the Android Reader app.

Repository owner configured for this project: **`naveedeme`**

## What is included

- Wiktionary/Kaikki JSONL streaming importer
- Princeton WordNet 3.0 importer
- FreeDict TEI importer with per-dictionary licence extraction
- Language-aware normalization for English, Urdu, Arabic and Persian
- SQLite indexes and FTS4 search compatible with Android SQLite
- Definitions, examples, forms, translations and lexical relations
- SHA-256 checksums, manifest validation and SQLite integrity checks
- GitHub Actions matrix builds
- GitHub Release publishing
- Stable application catalog URL
- Fixture tests for every importer
- Merged catalogs, so publishing one pack never removes unrelated packs
- Seven release-safe shards for the full English Wiktionary
- Android installation/search contract in `docs/ANDROID_INTEGRATION.md`

## Stable catalog URL for the Android app

```text
https://github.com/naveedeme/reader-dictionaries/releases/latest/download/catalog.json
```

The app should fetch this file, compare versions, download a pack, verify its SHA-256, safely extract it, validate `manifest.json`, open `dictionary.sqlite` read-only, and then atomically activate it.

## Create and push the repository

Create an empty public repository named `reader-dictionaries` under your GitHub account. Do not add a README or licence on GitHub because they are already included here.

From this project folder run:

```bash
git init
git add .
git commit -m "Initial offline dictionary builder"
git branch -M main
git remote add origin https://github.com/naveedeme/reader-dictionaries.git
git push -u origin main
```

No personal access token or custom secret is required for normal builds. The workflow uses the repository's built-in `GITHUB_TOKEN` to create releases.

For a one-command push after creating the empty GitHub repository, use either:

```powershell
./push-to-github.ps1
```

or on Linux/macOS/Git Bash:

```bash
./push-to-github.sh
```

## First build

1. Open the repository on GitHub.
2. Open **Actions**.
3. Select **Build Dictionary Packs**.
4. Click **Run workflow**.
5. Enter `core` as the selection.
6. Keep **Publish a GitHub Release** enabled.

The `core` group builds:

- English Lite
- Princeton WordNet
- Urdu–English
- Arabic–English
- Hindi–English
- Persian–English

When it completes, open **Releases**. The latest release will contain dictionary ZIP files, checksum files and `catalog.json`.

## Build selections

The workflow accepts either a group or one exact pack ID.

| Selection | Purpose |
|---|---|
| `core` | Smallest useful multilingual release |
| `standard` | Core plus Spanish, French, German and Turkish to English |
| `native` | Spanish, French, German and Turkish native-definition packs |
| `bilingual` | FreeDict bilingual packs |
| `large` | Seven full-English Wiktionary shards |
| `all` | Every enabled pack; expensive |
| exact pack ID | Build only one pack, such as `wiktionary-ur-en` |

The monthly schedule builds `standard`. Large English shards and FreeDict groups remain manual so a heavy or temporarily unavailable upstream source does not block the regular catalog. Publishing any group merges the previous catalog; dictionaries not rebuilt in that run remain listed with their immutable older release URLs.

## Package format

Every ZIP contains:

```text
manifest.json
dictionary.sqlite
LICENSE.txt
ATTRIBUTION.md
```

The SQLite schema contains:

```text
metadata
entries
senses
examples
forms
translations
relations
entries_fts
```

Useful Android queries:

```sql
-- Exact headword
SELECT *
FROM entries
WHERE normalized_headword = ?;

-- Match an inflected form
SELECT e.*
FROM forms f
JOIN entries e ON e.id = f.entry_id
WHERE f.normalized_form = ?;

-- Prefix suggestions
SELECT headword
FROM entries
WHERE normalized_headword >= ?
  AND normalized_headword < ?
ORDER BY normalized_headword
LIMIT 20;

-- FTS search
SELECT rowid
FROM entries_fts
WHERE entries_fts MATCH ?
LIMIT 50;
```

For prefix search, pass the normalized prefix as the lower bound and prefix plus a high Unicode sentinel as the upper bound.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows
python -m pip install -r requirements.txt
make verify
```

List a build matrix:

```bash
python scripts/list_packs.py --group core --pretty
```

Build one real source locally:

```bash
python scripts/download_source.py --pack wiktionary-ur-en --output work/wiktionary-ur-en
python scripts/build_pack.py --pack wiktionary-ur-en --source work/wiktionary-ur-en --output dist
python scripts/validate_pack.py dist/wiktionary-ur-en-*.zip --config config/dictionaries.yml
```

## Adding another dictionary

Add a pack to `config/dictionaries.yml` with:

- unique `id`
- title and description
- source and definition language codes
- licence
- build groups
- smoke-test words
- source type and location

Supported source types are `wiktionary`, `wordnet`, and `freedict`. FreeDict supports `mode: git` for hand-maintained dictionaries and `mode: generated` for official generated TEI dictionaries that are not present in the Git repository.

## Source and size considerations

Kaikki's language-specific postprocessed downloads are convenient but are marked for eventual removal. Each configured pack therefore includes the full English Wiktextract dump as a fallback where appropriate. That fallback is much larger, so it should only be used when the primary URL disappears.

The full English Wiktionary is intentionally excluded from `core` and `standard`. It is divided into seven logical shards (`A–D`, `E–H`, `I–L`, `M–P`, `Q–T`, `U–Z`, and other initials) to keep individual assets below GitHub's per-file limit; validation rejects an oversized package before publishing. Build all shards with selection `large`, or build one exact shard such as `wiktionary-en-full-a-d`. Each shard downloads the large upstream source independently, so this group is intentionally manual. The catalog exposes `logicalId` and `shard` metadata so the Android app can group the seven downloads as one optional dictionary.

## Android integration contract

Read these before adding the store to the Reader app:

- `docs/ANDROID_INTEGRATION.md` — safe WorkManager installation, rollback, normalization and queries
- `docs/PACK_FORMAT.md` — package and compatibility contract
- `schema/manifest.schema.json` — manifest shape
- `schema/catalog.schema.json` — catalog shape

Inspect a generated package locally with:

```bash
python scripts/query_pack.py dist/<dictionary>.zip book
```

## Publishing and immutability

Workflow artifacts are temporary and are used only to move files between jobs. The Android app downloads from GitHub Releases. Each release receives a unique tag, and `catalog.json` contains exact versioned asset URLs and SHA-256 values. The workflow first downloads the previous catalog and replaces only the packs built in the current run. GitHub's `/releases/latest/download/catalog.json` redirect therefore exposes the newest complete merged catalog.

Do **not** delete an older dictionary release while the current catalog still references assets from it. A partial rebuild intentionally preserves unchanged packs by retaining their immutable URLs from earlier releases. Rebuild those packs first, publish the merged catalog, and only then remove an unreferenced old release.

## Licence responsibilities

The builder code is MIT licensed. Dictionary data is not.

- Wiktionary packs include CC BY-SA 4.0 legal text and attribution.
- WordNet packs include Princeton's WordNet 3.0 licence.
- FreeDict licences vary per dictionary and are extracted from each TEI header.

Review generated `LICENSE.txt` and `ATTRIBUTION.md` before publishing a newly added source.
