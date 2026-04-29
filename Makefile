PYTHON = .venv/bin/python
PIP = .venv/bin/pip

venv:
	if [ ! -d ".venv" ]; then python -m venv .venv; fi
	$(PIP) install -q -r requirements_dev.txt

# Explicit subdirs for per-file Python formatters (autoflake/docformatter/black).
# Do NOT change to ".": docformatter's recursive walk has a bug where hitting
# .venv calls `break` and aborts the whole walk, returning 0 files (treated as
# FormatResult.error → exit 1). Add new top-level Python packages here.
PY_DIRS = dags tests iac

format: venv
	$(PYTHON) -m autoflake $(PY_DIRS)
	$(PYTHON) -m docformatter --in-place $(PY_DIRS) || { ec=$$?; if [ $$ec -eq 3 ]; then true; else exit $$ec; fi; }
	$(PYTHON) -m black -q $(PY_DIRS)
	$(PYTHON) -m sqlfluff fix -q --disable-progress-bar --processes 0

check-format: venv
	@failed=0; \
	echo "Checking: autoflake"; $(PYTHON) -m autoflake --check $(PY_DIRS) || { failed=1; }; \
	echo "Checking: docformatter"; $(PYTHON) -m docformatter --check $(PY_DIRS) || { failed=1; }; \
	echo "Checking: black"; $(PYTHON) -m black --check $(PY_DIRS) || { failed=1; }; \
	echo "Checking: sqlfluff"; $(PYTHON) -m sqlfluff lint --disable-progress-bar --processes 0 || { failed=1; }; \
	exit $$failed

test: venv
	$(PYTHON) -m pytest tests --cov

delete-venv:
	rm -rf .venv
