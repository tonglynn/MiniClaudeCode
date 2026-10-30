import pytest
from app import safe_divide

@pytest.mark.parametrize('args,expected',[([5, 2], 2.5), ([3, 0], None)])
def test_visible(args,expected):
    assert safe_divide(*args)==expected
