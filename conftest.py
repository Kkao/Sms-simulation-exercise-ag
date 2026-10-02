import shutil
from pathlib import Path
from uuid import uuid4

import pytest

_GENERATED_BASE_TEMP: pytest.StashKey[Path] = pytest.StashKey()
_TEMP_PREFIX = ".pytest-tmp-"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Give each test process a private temporary directory in the checkout."""
    if config.option.basetemp is not None:
        return

    base_temp = Path(config.rootpath) / f"{_TEMP_PREFIX}{uuid4().hex}"
    config.option.basetemp = str(base_temp)
    config.stash[_GENERATED_BASE_TEMP] = base_temp


def pytest_unconfigure(config: pytest.Config) -> None:
    """Remove only the temporary directory generated for this test process."""
    base_temp = config.stash.get(_GENERATED_BASE_TEMP, None)
    if base_temp is None:
        return

    root = Path(config.rootpath).resolve()
    if base_temp.parent.resolve() == root and base_temp.name.startswith(_TEMP_PREFIX):
        shutil.rmtree(base_temp, ignore_errors=True)
