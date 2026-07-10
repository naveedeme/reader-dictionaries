# Third-party data notices

This repository contains builder code, not the dictionary datasets themselves.
Generated packs preserve source attribution and licence material.

- **Wiktionary / Wiktextract / Kaikki:** Wiktionary text is reused under its applicable Wikimedia licensing terms. Generated packs include attribution, a source URL, an extraction date, and the CC BY-SA 4.0 legal text supplied in `config/licenses/CC-BY-SA-4.0.txt`.
- **Princeton WordNet 3.0:** generated packs include Princeton's WordNet 3.0 licence from `config/licenses/WORDNET-3.0.txt`.
- **FreeDict:** every dictionary can have its own licence. Hand-maintained TEI sources are fetched from `fd-dictionaries`; generated English–Spanish and English/German pairs are fetched from FreeDict's official generated service. The builder packages the source `COPYING` file and TEI availability statement. Review that text before publishing a newly added FreeDict pack.

The repository's MIT licence applies only to the builder code and documentation, not to generated dictionary data.
