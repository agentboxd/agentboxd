import re
from pathlib import Path

import pytest

from agentboxd import __version__

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@pytest.mark.skipif(not PYPROJECT.is_file(), reason="pyproject.toml not available (installed package)")
def test_version_matches_pyproject() -> None:
    match = re.search(r'^version = "([^"]+)"$', PYPROJECT.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None
    assert __version__ == match.group(1)
