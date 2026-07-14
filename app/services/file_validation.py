"""
File validation service.

BRD requirement: "System must gracefully handle and provide clear feedback
for: corrupted/unreadable files, files too large, wrong formats, empty
uploads, duplicate files, document sets with no extractable text."

We validate everything we CAN check at upload time here (size, extension,
emptiness, corruption-at-the-byte-level, duplicates within the same job).
"No extractable text" needs real parsing (PDF/DOCX text extraction), which
is Milestone 2 scope -- flagged below so it isn't silently forgotten.
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document

settings = get_settings()


@dataclass
class ValidationResult:
    is_valid: bool
    reason: str | None = None
    file_hash: str | None = None
    file_bytes: bytes | None = None


def _has_valid_extension(filename: str) -> bool:
    return Path(filename).suffix.lower() in settings.ALLOWED_EXTENSIONS


def _looks_corrupted(file_bytes: bytes, filename: str) -> bool:
    """
    Minimal magic-byte sanity check. Not a full corruption scanner --
    that's overkill for M1 -- but catches the common "renamed .txt to .pdf"
    or truncated-download case before it wastes downstream processing.
    """
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return not file_bytes.startswith(b"%PDF-")
    if suffix in (".docx", ".xlsx"):
        # docx/xlsx are zip containers
        return not file_bytes.startswith(b"PK")
    return False  # txt/csv/doc: no reliable magic bytes to check here


async def validate_upload(
    file: UploadFile,
    review_job_id,
    db: AsyncSession,
) -> ValidationResult:
    file_bytes = await file.read()
    await file.seek(0)

    # 1. Empty upload
    if len(file_bytes) == 0:
        return ValidationResult(False, reason="File is empty (0 bytes).")

    # 2. Too large
    if len(file_bytes) > settings.max_file_size_bytes:
        size_mb = len(file_bytes) / (1024 * 1024)
        return ValidationResult(
            False,
            reason=f"File is {size_mb:.1f} MB, which exceeds the {settings.MAX_FILE_SIZE_MB} MB limit.",
        )

    # 3. Wrong / unsupported format
    if not _has_valid_extension(file.filename or ""):
        allowed = ", ".join(settings.ALLOWED_EXTENSIONS)
        return ValidationResult(False, reason=f"Unsupported file type. Allowed types: {allowed}")

    # 4. Corrupted / unreadable (magic-byte check)
    if _looks_corrupted(file_bytes, file.filename or ""):
        return ValidationResult(False, reason="File appears corrupted or does not match its extension.")

    # 5. Duplicate within this review job (content hash, not just filename)
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    existing = await db.execute(
        select(Document).where(
            Document.review_job_id == review_job_id,
            Document.file_hash == file_hash,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return ValidationResult(False, reason="This exact file has already been uploaded to this review.")

    # NOTE: "document set has no extractable text" is validated at the SET
    # level after text extraction runs (Milestone 2), not per-file here.

    return ValidationResult(True, file_hash=file_hash, file_bytes=file_bytes)
