# Contributing

1. Add or edit a pack in `config/dictionaries.yml`.
2. Keep source and data licences intact.
3. Add a smoke-test word that is expected to exist in the source.
4. Run `python -m pytest -q`.
5. Run a local fixture build with `make test-build`.
6. Do not commit generated databases, source dumps, ZIP files, or checksums.

A dictionary source must permit redistribution. If its licence is unclear, do not add it.
