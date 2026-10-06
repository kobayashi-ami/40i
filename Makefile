# Phase 0 targets. dev / up arrive in Phase 1.
PY := $(shell command -v uv >/dev/null 2>&1 && echo "uv run --group design python" || echo python3)

.PHONY: mockups mockups-hires lint

mockups:
	$(PY) design/render_mockups.py

mockups-hires:
	$(PY) design/render_mockups.py --hires

lint:
	ruff check design && ruff format --check design
