import pytest
from app import merge_intervals

@pytest.mark.parametrize('args,expected',[([[[5, 7], [1, 3], [3, 6]]], [[1, 7]]), ([[]], [])])
def test_visible(args,expected):
    assert merge_intervals(*args)==expected
