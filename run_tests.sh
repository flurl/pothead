#!/bin/sh

if [ -f "venv/bin/pytest" ]; then
    PYTEST_CMD="venv/bin/pytest"
else
    PYTEST_CMD="pytest"
fi

POTHEAD_SIGNAL_ACCOUNT="test" POTHEAD_GEMINI_API_KEY="test" POTHEAD_SUPERUSER="test" POTHEAD_ENABLED_PLUGINS='["echo", "gemini"]' PYTHONPATH=. $PYTEST_CMD
