import pytest
from app import days_between

@pytest.mark.parametrize('args,expected',[(['2024-02-28', '2024-03-01'], 2), (['2026-01-02', '2026-01-01'], -1)])
def test_visible(args,expected):
    assert days_between(*args)==expected
