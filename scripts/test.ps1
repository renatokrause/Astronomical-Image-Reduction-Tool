$ErrorActionPreference = "Stop"

python -m pip install -r requirements-dev.txt
pytest
