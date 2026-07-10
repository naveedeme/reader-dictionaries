# Android dictionary-store integration

The Android app consumes one stable catalog URL:

```text
https://github.com/naveedeme/reader-dictionaries/releases/latest/download/catalog.json
```

The catalog contains exact immutable release URLs for each dictionary package. A later one-pack build merges the previous catalog, so packs that were not rebuilt remain available.

## Recommended components

- `DictionaryCatalogClient`: fetches and parses `catalog.json`
- `DictionaryPackRepository`: tracks installed pack id, version, path and state
- `DictionaryDownloadWorker`: downloads, verifies and installs a pack
- `OfflineDictionaryDatabase`: opens one installed SQLite file read-only
- `OfflineDictionarySearch`: performs exact, form, prefix and FTS lookups
- `DictionaryLicenseScreen`: displays `LICENSE.txt` and `ATTRIBUTION.md`

Use app-specific persistent storage, not the cache directory. A suitable layout is:

```text
files/dictionaries/
├── registry.json
├── installed/
│   └── <pack-id>/
│       └── <version>/
│           ├── manifest.json
│           ├── dictionary.sqlite
│           ├── LICENSE.txt
│           └── ATTRIBUTION.md
└── staging/
```

## Safe installation algorithm

1. Fetch the catalog over HTTPS.
2. Select a pack compatible with the app's supported schema version.
3. Download the ZIP into `staging/<random>.part`.
4. Calculate SHA-256 while downloading or immediately afterwards.
5. Compare it with the catalog's `sha256` value.
6. Extract into a new temporary directory.
7. Reject absolute paths, `..` traversal, links and unexpected top-level files.
8. Parse `manifest.json` and confirm that its id/version match the catalog entry.
9. Verify `dictionary.sqlite` against `manifest.databaseSha256`.
10. Open the database read-only and check:
    - `PRAGMA integrity_check` returns `ok`
    - `PRAGMA user_version` is supported
    - required tables exist
    - entry count matches the manifest
11. Atomically rename the temporary directory into `installed/<id>/<version>`.
12. Atomically update the local registry.
13. Remove the previous version only after the new version opens successfully.

Never activate a package merely because ZIP extraction succeeded.

## Lookup order

For a selected word, use this order:

1. Exact `entries.normalized_headword`
2. Exact `forms.normalized_form`, joined back to `entries`
3. Prefix suggestions
4. FTS search when the user explicitly searches definitions or related words
5. Existing online dictionary providers
6. Optional AI fallback

## Core SQL

### Exact headword

```sql
SELECT id, headword, part_of_speech, pronunciation, etymology
FROM entries
WHERE normalized_headword = ?
ORDER BY headword, part_of_speech;
```

### Inflected form to lemma

```sql
SELECT DISTINCT e.id, e.headword, e.part_of_speech, e.pronunciation
FROM forms AS f
JOIN entries AS e ON e.id = f.entry_id
WHERE f.normalized_form = ?
ORDER BY e.headword, e.part_of_speech;
```

### Definitions

```sql
SELECT sense_order, definition, tags_json, topics_json
FROM senses
WHERE entry_id = ?
ORDER BY sense_order;
```

### Examples

```sql
SELECT x.example_text, x.translation, x.reference_text
FROM examples AS x
JOIN senses AS s ON s.id = x.sense_id
WHERE s.entry_id = ?
ORDER BY s.sense_order, x.id;
```

### Relations

```sql
SELECT relation_type, related_word
FROM relations
WHERE entry_id = ?
ORDER BY relation_type, related_word;
```

### Prefix suggestions

```sql
SELECT DISTINCT headword
FROM entries
WHERE normalized_headword >= ?
  AND normalized_headword < ?
ORDER BY normalized_headword
LIMIT 30;
```

The lower bound is the normalized prefix. The upper bound can be the normalized prefix followed by `\uFFFF`.

### FTS4

```sql
SELECT e.id, e.headword
FROM entries_fts AS f
JOIN entries AS e ON e.id = f.rowid
WHERE entries_fts MATCH ?
LIMIT 50;
```

Escape or quote user input before creating an FTS query. Do not concatenate arbitrary FTS operators from untrusted text.

## Normalization contract

The app must mirror `scripts/common.py::normalize_word`:

- Unicode NFKC
- trim and collapse whitespace
- Unicode case-folding
- Arabic/Persian/Urdu diacritic and tatweel removal
- Arabic alef/yeh normalization
- Persian and Urdu kaf/yeh normalization

Keep the original selected text for display and copying; use only the normalized value for lookup.

## Multiple installed packs

A lookup can query all enabled packs whose `sourceLanguage` matches the detected or selected word language. Present results grouped by pack, with the user's preferred dictionary first. Bilingual packs use `definitionLanguage` to indicate the result language.

Do not merge entries from separately licensed packs into a new database on the device. Keeping each pack intact makes updates, removal and attribution straightforward.

## Updates and rollback

Compare versions as opaque release strings unless the app adopts the repository's `YYYY.MM.DD.RUN` convention. Download updates into staging and keep the old version until validation completes. If activation fails, leave the old registry entry untouched.

## Removal

Closing all SQLite handles must happen before deleting an installed pack. Delete only the selected pack/version directory and its registry entry. Licence and attribution files are removed together with the pack.
