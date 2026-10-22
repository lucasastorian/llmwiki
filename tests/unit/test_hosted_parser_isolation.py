"""Fail-closed configuration tests for hosted parser isolation."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from config import Settings
from pydantic import ValidationError


def _settings(**overrides) -> Settings:
    values = {
        "MODE": "hosted",
        "S3_BUCKET": "",
        "CONVERTER_URL": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("global_ocr_enabled", [True, False])
def test_hosted_uploads_require_converter_even_if_ocr_kill_switch_is_off(
    global_ocr_enabled,
):
    with pytest.raises(ValidationError, match="CONVERTER_URL is required"):
        _settings(
            S3_BUCKET="test-bucket",
            CONVERTER_URL="   ",
            GLOBAL_OCR_ENABLED=global_ocr_enabled,
        )


def test_hosted_uploads_accept_isolated_converter():
    settings = _settings(
        S3_BUCKET="test-bucket",
        CONVERTER_URL="https://converter.internal",
        CONVERTER_SECRET="test-converter-secret",
    )
    assert settings.CONVERTER_URL == "https://converter.internal"


def test_hosted_uploads_require_converter_authentication():
    with pytest.raises(ValidationError, match="CONVERTER_SECRET is required"):
        _settings(
            S3_BUCKET="test-bucket",
            CONVERTER_URL="https://converter.internal",
            CONVERTER_SECRET="   ",
        )


def test_hosted_mode_without_upload_service_does_not_require_converter():
    settings = _settings(S3_BUCKET="")
    assert settings.CONVERTER_URL == ""


def test_hosted_uploads_enabled_by_bucket_alone_without_static_keys():
    with pytest.raises(ValidationError, match="CONVERTER_URL is required"):
        _settings(S3_BUCKET="test-bucket")


def test_s3_bucket_defaults_to_disabled():
    assert Settings(_env_file=None, MODE="hosted").S3_BUCKET == ""


def test_local_uploads_keep_in_process_parsing_available():
    settings = _settings(
        MODE="local",
        S3_BUCKET="test-bucket",
        CONVERTER_URL="",
    )
    assert settings.MODE == "local"


def test_importing_hosted_ocr_does_not_import_pdf_parser():
    api_dir = Path(__file__).resolve().parents[2] / "api"
    env = {
        **os.environ,
        "PYTHONPATH": str(api_dir),
        "MODE": "hosted",
        "S3_BUCKET": "",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import services.ocr; "
            "assert 'services.pdf_extract' not in sys.modules; "
            "assert 'opendataloader_pdf' not in sys.modules",
        ],
        cwd=api_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
