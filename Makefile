PYTHON = .venv/bin/python
PIP = .venv/bin/pip

venv:
	if [ ! -d ".venv" ]; then python -m venv .venv; fi
	$(PIP) install -q -r requirements_dev.txt

format: venv
	$(PYTHON) -m autoflake .
	$(PYTHON) -m docformatter --in-place . || { if [ $$? -eq 1 ]; then true; else exit 1; fi; }
	$(PYTHON) -m black -q .
	$(PYTHON) -m sqlfluff fix -q --disable-progress-bar --processes 0

check-format: venv
	@failed=0; \
	echo "Checking: autoflake"; $(PYTHON) -m autoflake --check . || { failed=1; }; \
	echo "Checking: docformatter"; $(PYTHON) -m docformatter --check . || { failed=1; }; \
	echo "Checking: black"; $(PYTHON) -m black --check . || { failed=1; }; \
	echo "Checking: sqlfluff"; $(PYTHON) -m sqlfluff lint --disable-progress-bar --processes 0 || { failed=1; }; \
	exit $$failed

test: venv
	$(PYTHON) -m pytest tests --cov

delete-venv:
	rm -rf .venv
