.PHONY: benchmark-db check compile eval index-corpus lint migrate test test-api test-db typecheck

PYTHON ?= python3
export PYTHONPATH := src

test:
	$(PYTHON) -m unittest discover -s tests -v

test-api:
	$(PYTHON) -m unittest discover -s integration_tests -v

test-db:
	$(PYTHON) -m unittest integration_tests.test_postgres_retrieval -v

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy src tests integration_tests scripts

eval:
	$(PYTHON) scripts/run_eval.py

migrate:
	$(PYTHON) scripts/migrate.py

index-corpus:
	$(PYTHON) scripts/index_corpus.py

benchmark-db:
	$(PYTHON) scripts/benchmark_retrieval.py --documents 500 --iterations 50 \
		--output artifacts/benchmarks/pgvector-ci.json

compile:
	$(PYTHON) -m compileall -q src scripts tests integration_tests

check: lint typecheck compile test test-api eval
