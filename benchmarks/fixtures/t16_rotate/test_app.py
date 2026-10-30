import pytest
from app import rotate

@pytest.mark.parametrize('args,expected',[([[1, 2, 3, 4], 1], [4, 1, 2, 3]), ([[1, 2, 3], -1], [2, 3, 1])])
def test_visible(args,expected):
    assert rotate(*args)==expected
