# Dictionary package format v1

Every release asset is a ZIP with exactly these required files at its root:

```text
manifest.json
 dictionary.sqlite
LICENSE.txt
ATTRIBUTION.md
```

`dictionary.sqlite` uses `PRAGMA user_version = 1`. The authoritative SQL definition is `schema/dictionary.sql`.

## Manifest fields

| Field | Meaning |
|---|---|
| `schemaVersion` | Package/database schema version |
| `id` | Stable dictionary pack identifier |
| `version` | Immutable build version |
| `sourceType` | `wiktionary`, `wordnet` or `freedict` |
| `sourceLanguage` | ISO-style headword language code |
| `definitionLanguage` | Language used by definitions/translations |
| `license` | Short licence identifier/description |
| `databaseFile` | Currently `dictionary.sqlite` |
| `databaseSha256` | SHA-256 of the uncompressed database |
| `installedSize` | Approximate bytes after extraction |
| `entryCount` | Number of rows in `entries` |
| `minimumAppSchemaVersion` | Minimum schema support required in the app |
| `source` | Upstream URL, revision, checksum and download metadata |

The release catalog adds archive-level SHA-256, download size and exact release URL.

## Database model

- `entries`: headwords and entry-level metadata
- `senses`: ordered definitions
- `examples`: examples attached to senses
- `forms`: inflections and alternate written forms
- `translations`: structured translations when supplied upstream
- `relations`: synonyms, antonyms and semantic relations
- `metadata`: package provenance stored inside SQLite
- `entries_fts`: FTS4 projection for searchable text

One lexical item can have several `entries` rows when it has different parts of speech or source senses. The app should group them for display rather than assuming headwords are unique.

## Compatibility rules

- Unknown optional JSON fields must be ignored.
- Unknown database columns may be ignored.
- A higher unsupported `schemaVersion` must not be opened.
- Package id/version must agree between the catalog and manifest.
- The archive checksum and database checksum must both pass.
- Licence and attribution files must remain accessible from the app.
