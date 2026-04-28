PYTHON = .venv/bin/python
PIP = .venv/bin/pip

venv:
	if [ ! -d ".venv" ]; then python -m venv .venv; fi
	$(PIP) install -q -r requirements_dev.txt

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
