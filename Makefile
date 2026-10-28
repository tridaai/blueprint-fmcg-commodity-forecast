# Trida AI Blueprint — Commodity Price Forecasting & Procurement
# Intelligence Agent (FMCG / food buyer)
#
# Primary workflow is uv (https://docs.astral.sh/uv/):
#   make install     uv sync --extra dev
#   make demo        generated dataset + planted checks, offline
#   make test        pytest
#   make evals       eval gate, offline (SQLite stack)
#   make harness     boot the API and exercise it over HTTP
#   make serve       the operations API on http://localhost:8000
#
# No uv? python3 -m venv .venv && source .venv/bin/activate, then:
#   make install-pip

UV ?= uv

.PHONY: install install-pip demo test evals harness serve

install:
	$(UV) sync --extra dev

install-pip:
	# The frozen set first, then the package itself with --no-deps:
	# the two steps never mix.
	python -m pip install -r constraints.txt
	python -m pip install --no-deps -e .

demo:
	$(UV) run python scripts/demo.py

test:
	$(UV) run pytest -q

evals:
	$(UV) run python evals/run_evals.py

harness:
	$(UV) run python scripts/local_harness.py

serve:
	$(UV) run fmcg-agent-serve
