"""Every test under tests/unit is a unit test, marked here by location.

ci-fast selects `-m "unit or ..."`, and a module that forgot its
`pytestmark` was silently never run there: 75 tests in six files. Marking
by directory means a new file cannot fall through the same way.
"""

from pathlib import Path

import pytest

_HERE = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.unit)
