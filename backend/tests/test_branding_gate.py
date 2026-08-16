from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "scripts" / "check_branding.py"

SPEC = importlib.util.spec_from_file_location("mantly_check_branding", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
BRANDING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRANDING)


def _copy_contract_fixture(destination: pathlib.Path) -> None:
    relative_paths = {
        "backend/pyproject.toml",
        "backend/uv.lock",
        *BRANDING.EXPECTED_PACKAGES,
        *(path.replace("package.json", "package-lock.json") for path in BRANDING.EXPECTED_PACKAGES),
        *BRANDING.REQUIRED_TEXT,
    }
    for relative in relative_paths:
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def test_repository_branding_contract_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), "--root", str(ROOT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["ok"] is True


def test_branding_validator_is_read_only(tmp_path: pathlib.Path) -> None:
    _copy_contract_fixture(tmp_path)
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    assert BRANDING.validate(tmp_path) == []

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_branding_validator_rejects_legacy_product_identifier(tmp_path: pathlib.Path) -> None:
    _copy_contract_fixture(tmp_path)
    legacy_identifier = "isa" + "rai-email-agent"
    (tmp_path / "unexpected.txt").write_text(legacy_identifier, encoding="utf-8")

    errors = BRANDING.validate(tmp_path)

    assert any("unexpected.txt" in error and "legacy application image" in error for error in errors)


def test_branding_validator_rejects_package_version_drift(tmp_path: pathlib.Path) -> None:
    _copy_contract_fixture(tmp_path)
    package_path = tmp_path / "admin" / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["version"] = "9.9.9"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    errors = BRANDING.validate(tmp_path)

    assert any("admin/package.json" in error and "0.1.0" in error for error in errors)


def test_volume_migration_is_backup_first_and_never_deletes() -> None:
    script = (ROOT / "scripts" / "migrate-compose-volumes.sh").read_text(encoding="utf-8")

    assert 'MODE="${1:-copy}"' in script
    assert "inventory)" in script
    assert "MANTLY_VERIFIED_BACKUP_BUNDLE is required" in script
    assert "Backup bundle checksum verification failed" in script
    assert script.rindex("verify_backup") < script.index(
        'docker compose --project-directory "$ROOT" stop'
    )
    assert "-v \"$source:/source:ro\"" in script
    assert "docker volume rm" not in script
    assert "docker compose up" not in script
    assert "docker compose start" not in script
