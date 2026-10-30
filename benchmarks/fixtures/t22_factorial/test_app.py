import pytest
from app import factorial

@pytest.mark.parametrize('args,expected',[([0], 1), ([5], 120)])
def test_visible(args,expected):
    assert factorial(*args)==expected
