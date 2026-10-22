"""Shared fixtures for the FAP Manager tests (put the UKG Tools folder on the path)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fap_fakes import FakeUKG, super_access, perm   # noqa: E402
from openpyxl import Workbook                        # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Logs go to tmp, and no test touches the real credential store."""
    import ukg_api_tool as uat
    import ukg_env
    monkeypatch.setattr(uat, 'LOG_DIR', tmp_path / 'log')
    monkeypatch.setattr(ukg_env, 'remember_profile', lambda *a, **k: None)


@pytest.fixture
def ukg():
    return FakeUKG()


@pytest.fixture
def make_excel(tmp_path):
    """make_excel(rows, name='f.xlsx', headers=None) -> path. rows: [cp, ADD, EDIT, DELETE, VIEW, scope]."""
    def _make(rows, name='f.xlsx', headers=None):
        wb = Workbook()
        ws = wb.active
        ws.append(headers or ['Control Point', 'ADD', 'EDIT', 'DELETE', 'VIEW', 'scopeName'])
        for r in rows:
            ws.append(r)
        path = tmp_path / name
        wb.save(path)
        return path
    return _make
