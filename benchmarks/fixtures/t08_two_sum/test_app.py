import pytest
from app import two_sum

@pytest.mark.parametrize('args,expected',[([[1, 2, 4, 8], 10], [1, 3]), ([[3, 3], 6], [0, 1])])
def test_visible(args,expected):
    assert two_sum(*args)==expected
