PYTHON ?= python

.PHONY: install validate test test-build verify list-core clean

install:
	$(PYTHON) -m pip install -r requirements.txt

validate:
	$(PYTHON) -m compileall -q scripts
	$(PYTHON) scripts/validate_config.py

test: validate
	$(PYTHON) -m pytest -q

test-build:
	rm -rf build/test-dist
	$(PYTHON) scripts/build_pack.py --config tests/fixtures/dictionaries.test.yml --pack fixture-wiktionary --source tests/fixtures/wiktionary --output build/test-dist --version test
	$(PYTHON) scripts/validate_pack.py build/test-dist/fixture-wiktionary-test.zip --config tests/fixtures/dictionaries.test.yml
	$(PYTHON) scripts/build_pack.py --config tests/fixtures/dictionaries.test.yml --pack fixture-freedict --source tests/fixtures/freedict --output build/test-dist --version test
	$(PYTHON) scripts/validate_pack.py build/test-dist/fixture-freedict-test.zip --config tests/fixtures/dictionaries.test.yml
	$(PYTHON) scripts/build_pack.py --config tests/fixtures/dictionaries.test.yml --pack fixture-wordnet --source tests/fixtures/wordnet --output build/test-dist --version test
	$(PYTHON) scripts/validate_pack.py build/test-dist/fixture-wordnet-test.zip --config tests/fixtures/dictionaries.test.yml

verify: test test-build

list-core:
	$(PYTHON) scripts/list_packs.py --group core --pretty

clean:
	rm -rf build dist work site .pytest_cache scripts/__pycache__ tests/__pycache__
