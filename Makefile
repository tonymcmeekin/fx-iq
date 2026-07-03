setup:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

start:
	cd backend && . .venv/bin/activate && python -m uvicorn app.main:app --reload

test:
	cd backend && . .venv/bin/activate && PYTHONPATH=. pytest

lint:
	cd backend && . .venv/bin/activate && ruff check app

format:
	cd backend && . .venv/bin/activate && ruff format app
