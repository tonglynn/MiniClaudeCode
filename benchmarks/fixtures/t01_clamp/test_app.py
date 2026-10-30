import pytest
from app import clamp

@pytest.mark.parametrize('args,expected',[([5, 0, 10], 5), ([-2, 0, 10], 0)])
def test_visible(args,expected):
    assert clamp(*args)==expected
