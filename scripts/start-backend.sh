#!/bin/bash
cd "$(dirname "$0")/../backend" || exit
source .venv/bin/activate
python -m uvicorn app.main:app --reload
