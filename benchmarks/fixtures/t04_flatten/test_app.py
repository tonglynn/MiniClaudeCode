import pytest
from app import flatten

@pytest.mark.parametrize('args,expected',[([[1, [2, [3]], 4]], [1, 2, 3, 4]), ([[]], [])])
def test_visible(args,expected):
    assert flatten(*args)==expected
