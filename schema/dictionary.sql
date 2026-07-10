PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE entries (
    id INTEGER PRIMARY KEY,
    headword TEXT NOT NULL,
    normalized_headword TEXT NOT NULL,
    language_code TEXT NOT NULL,
    definition_language_code TEXT NOT NULL,
    part_of_speech TEXT,
    pronunciation TEXT,
    etymology TEXT,
    source_entry_id TEXT
);

CREATE INDEX idx_entries_normalized
ON entries(normalized_headword);

CREATE INDEX idx_entries_language
ON entries(language_code, normalized_headword);

CREATE TABLE senses (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    sense_order INTEGER NOT NULL,
    definition TEXT NOT NULL,
    tags_json TEXT,
    topics_json TEXT
);

CREATE INDEX idx_senses_entry
ON senses(entry_id, sense_order);

CREATE TABLE examples (
    id INTEGER PRIMARY KEY,
    sense_id INTEGER NOT NULL REFERENCES senses(id) ON DELETE CASCADE,
    example_text TEXT NOT NULL,
    translation TEXT,
    reference_text TEXT
);

CREATE INDEX idx_examples_sense
ON examples(sense_id);

CREATE TABLE forms (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    form TEXT NOT NULL,
    normalized_form TEXT NOT NULL,
    tags_json TEXT
);

CREATE INDEX idx_forms_normalized
ON forms(normalized_form);

CREATE INDEX idx_forms_entry
ON forms(entry_id);

CREATE TABLE translations (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    sense_text TEXT,
    target_language_code TEXT,
    translated_word TEXT NOT NULL,
    romanization TEXT,
    tags_json TEXT
);

CREATE INDEX idx_translations_entry
ON translations(entry_id);

CREATE TABLE relations (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    related_word TEXT NOT NULL,
    normalized_related_word TEXT NOT NULL
);

CREATE INDEX idx_relations_entry
ON relations(entry_id, relation_type);

CREATE INDEX idx_relations_word
ON relations(normalized_related_word);

CREATE VIRTUAL TABLE entries_fts USING fts4(
    headword,
    normalized_headword,
    definitions,
    forms,
    relations,
    tokenize=unicode61
);
