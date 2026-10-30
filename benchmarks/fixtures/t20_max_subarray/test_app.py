import pytest
from app import max_subarray

@pytest.mark.parametrize('args,expected',[([[-2, 1, -3, 4, -1, 2, 1, -5, 4]], 6), ([[-4, -2, -9]], -2)])
def test_visible(args,expected):
    assert max_subarray(*args)==expected
