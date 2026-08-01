.PHONY: check compile eval lint test test-api typecheck

PYTHON ?= python3
export PYTHONPATH := src

test:
	$(PYTHON) -m unittest discover -s tests -v

test-api:
	$(PYTHON) -m unittest discover -s integration_tests -v

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy src tests integration_tests scripts

eval:
	$(PYTHON) scripts/run_eval.py

compile:
	$(PYTHON) -m compileall -q src scripts tests integration_tests

check: lint typecheck compile test test-api eval
