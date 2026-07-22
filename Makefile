setup:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"

start:
	cd backend && . .venv/bin/activate && python -m uvicorn app.main:app --reload

test:
	cd backend && . .venv/bin/activate && pytest

lint:
	cd backend && . .venv/bin/activate && ruff check app tests scripts/check_source_privacy.py

privacy:
	cd backend && . .venv/bin/activate && python scripts/check_source_privacy.py

format:
	cd backend && . .venv/bin/activate && ruff format app tests scripts/check_source_privacy.py

check:
	make lint
	make privacy
	make test
