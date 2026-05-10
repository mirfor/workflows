.PHONY: help install test cov lint type sonar regen validate clean

help:
	@echo "Targets:"
	@echo "  install   — uv sync --all-extras"
	@echo "  test      — uv run pytest"
	@echo "  cov       — pytest + coverage.xml (do Sonara)"
	@echo "  lint      — ruff check + format check"
	@echo "  type      — mypy"
	@echo "  sonar     — cov + sonar-scanner (wymaga SONAR_TOKEN env lub sonar.token w properties)"
	@echo "  regen     — regenerate wszystkich Blueprintów (multi-tenant)"
	@echo "  validate  — bulk walidacja IR per Tenant"
	@echo "  clean     — usuń coverage, __pycache__, .scannerwork"

install:
	uv sync --all-extras

test:
	uv run pytest

cov:
	uv run pytest \
		--cov=ir --cov=mapper --cov=validator --cov=generator \
		--cov=activities --cov=scripts \
		--cov-report=xml --cov-report=term

lint:
	uv run ruff check ir mapper validator generator activities scripts tests worker.py
	uv run ruff format --check ir mapper validator generator activities scripts tests worker.py

type:
	uv run mypy mapper validator generator activities scripts

sonar: cov
	sonar-scanner $(if $(SONAR_TOKEN),-Dsonar.token=$(SONAR_TOKEN),) $(if $(SONAR_HOST_URL),-Dsonar.host.url=$(SONAR_HOST_URL),)

regen:
	uv run python -m scripts.regenerate_all

validate:
	uv run python -m scripts.validate_all --strict

clean:
	rm -rf coverage.xml .coverage .coverage.* htmlcov .scannerwork
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
