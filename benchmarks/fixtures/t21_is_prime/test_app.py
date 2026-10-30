import pytest
from app import is_prime

@pytest.mark.parametrize('args,expected',[([2], True), ([9], False)])
def test_visible(args,expected):
    assert is_prime(*args)==expected
