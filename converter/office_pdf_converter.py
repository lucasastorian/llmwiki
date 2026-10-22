"""Office-to-PDF conversion via a private, killable LibreOffice instance."""

from pathlib import Path

from converter import process_group
from converter.config import ConverterConfig


class OfficePdfConverter:
    def __init__(self, config: ConverterConfig) -> None:
        self._config = config

    def convert(self, source_path: Path, tmpdir: str) -> Path:
        # Per-conversion profile avoids lock contention that leaves zombie soffice/Java processes.
        profile = f"file://{tmpdir}/lo-profile"
        process_group.run_in_process_group(
            [
                "libreoffice", f"-env:UserInstallation={profile}",
                "--headless", "--norestore", "--nofirststartwizard",
                "--convert-to", "pdf", "--outdir", tmpdir, str(source_path),
            ],
            timeout=self._config.convert_timeout_seconds,
            what="LibreOffice",
        )
        pdf_path = Path(tmpdir) / f"{source_path.stem}.pdf"
        if not pdf_path.exists():
            raise RuntimeError("LibreOffice did not produce a PDF")
        return pdf_path
