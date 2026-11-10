"""deploy/run-local.ps1 checks the SHA256 of the PostgreSQL ZIP before unpacking it.

The check itself runs in PowerShell (Windows PowerShell or pwsh, both on the CI runners):
the real `Assert-Sha256` function from the script is called on a scratch file.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "deploy" / "run-local.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n")


def _function(name: str) -> str:
    match = re.search(rf"^function {name} \{{\n.*?^\}}\n", _source(), re.S | re.M)
    assert match, f"{name} not found in {SCRIPT.name}"
    return match.group(0)


def test_pinned_value_is_a_sha256():
    match = re.search(r'^\$PgZipSha256 = "([0-9A-F]+)"$', _source(), re.M)
    assert match and len(match.group(1)) == 64


def test_zip_is_checked_after_download_and_before_unpacking():
    src = _source()
    download = src.index("curl.exe -L -s --fail -o $zip $PgZipUrl")
    check = src.index("Assert-Sha256 -Path $zip -Expected $PgZipSha256")
    unpack = src.index("Expand-Archive -Path $zip")
    assert download < check < unpack
    assert "$LASTEXITCODE -ne 0" in src[download:check]  # a failed download stops the script too


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is not installed")
@pytest.mark.parametrize("matches", [True, False], ids=["matching", "tampered"])
def test_assert_sha256_stops_and_deletes_a_file_that_does_not_match(tmp_path, matches):
    zip_file = tmp_path / "pg.zip"
    zip_file.write_bytes(b"not really a zip")
    expected = hashlib.sha256(zip_file.read_bytes()).hexdigest().upper() if matches else "0" * 64
    runner = tmp_path / "check.ps1"
    runner.write_text(
        "$ErrorActionPreference = 'Stop'\n" + _function("Assert-Sha256")
        + f"Assert-Sha256 -Path '{zip_file}' -Expected '{expected}'\n'unpacked'\n",
        encoding="utf-8-sig",
    )
    # fixed argv: PowerShell from PATH and a script this test has just written
    r = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",  # noqa: S603
                        "-File", str(runner)], capture_output=True, text=True, timeout=120)
    if matches:
        assert r.returncode == 0, r.stderr
        assert "unpacked" in r.stdout and zip_file.exists()
    else:
        assert r.returncode != 0
        assert "unpacked" not in r.stdout and not zip_file.exists()
        assert "SHA256" in r.stdout + r.stderr
