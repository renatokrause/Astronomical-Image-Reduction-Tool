$ErrorActionPreference = "Stop"

python -m pip install -r requirements-dev.txt

ruff format --check .
ruff check .
pyright
bandit -c pyproject.toml -r src

if (Test-Path requirements.txt) {
    pip-audit --requirement requirements.txt --requirement requirements-dev.txt
} else {
    pip-audit --requirement requirements-dev.txt
}

pytest

vulture src tests --min-confidence 80
radon cc src -s -a
radon mi src -s
