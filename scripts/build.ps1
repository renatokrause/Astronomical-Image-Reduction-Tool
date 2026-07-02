$ErrorActionPreference = "Stop"

python -m pip install -r requirements-dev.txt

if (Test-Path airt.spec) {
    pyinstaller --noconfirm airt.spec
} else {
    pyinstaller --noconfirm --name AIRT --windowed src\airt\__main__.py
}
