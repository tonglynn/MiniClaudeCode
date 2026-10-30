import pytest
from app import transpose

@pytest.mark.parametrize('args,expected',[([[[1, 2, 3], [4, 5, 6]]], [[1, 4], [2, 5], [3, 6]]), ([[]], [])])
def test_visible(args,expected):
    assert transpose(*args)==expected
