setup:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"

start:
	cd backend && . .venv/bin/activate && python -m uvicorn app.main:app --reload

dashboard:
	backend/.venv/bin/python backend/scripts/run_dashboard.py

ai-trial:
	cd backend && . .venv/bin/activate && python scripts/run_simulated_hosted_ai_trial.py

test:
	cd backend && . .venv/bin/activate && pytest

lint:
	cd backend && . .venv/bin/activate && ruff check app tests scripts/check_source_privacy.py scripts/run_dashboard.py scripts/run_oanda_practice_canary_preflight.py scripts/run_oanda_practice_canary_rehearsal.py scripts/run_scheduled_practice_operation.py scripts/run_simulated_hosted_ai_trial.py

privacy:
	cd backend && . .venv/bin/activate && python scripts/check_source_privacy.py

format:
	cd backend && . .venv/bin/activate && ruff format app tests scripts/check_source_privacy.py scripts/run_dashboard.py scripts/run_oanda_practice_canary_preflight.py scripts/run_oanda_practice_canary_rehearsal.py scripts/run_scheduled_practice_operation.py scripts/run_simulated_hosted_ai_trial.py

check:
	make lint
	make privacy
	make test
