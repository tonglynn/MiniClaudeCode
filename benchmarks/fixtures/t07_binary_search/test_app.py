import pytest
from app import binary_search

@pytest.mark.parametrize('args,expected',[([[1, 3, 5, 7], 5], 2), ([[1, 3, 5], 4], -1)])
def test_visible(args,expected):
    assert binary_search(*args)==expected
