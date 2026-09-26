import base64
import mimetypes
import os
from typing import Optional, Union

from ._types import AttachmentInput

__all__ = ["attachment_from_bytes", "attachment_from_path"]

_DEFAULT_CONTENT_TYPE = "application/octet-stream"


def _guess(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or _DEFAULT_CONTENT_TYPE


def attachment_from_bytes(
    filename: str,
    data: Union[bytes, bytearray, memoryview],
    content_type: Optional[str] = None,
) -> AttachmentInput:
    """Build an attachment for ``messages.send`` / ``messages.reply`` from in-memory bytes.

    ``content_type`` is guessed from ``filename`` when omitted.
    """
    return {
        "filename": filename,
        "content_type": content_type or _guess(filename),
        "content_base64": base64.b64encode(bytes(data)).decode("ascii"),
    }


def attachment_from_path(
    path: Union[str, "os.PathLike[str]"],
    content_type: Optional[str] = None,
    *,
    filename: Optional[str] = None,
) -> AttachmentInput:
    """Read a file and build an attachment. ``content_type`` is guessed from the name when omitted."""
    name = filename or os.path.basename(os.fspath(path))
    with open(path, "rb") as f:
        data = f.read()
    return attachment_from_bytes(name, data, content_type)
