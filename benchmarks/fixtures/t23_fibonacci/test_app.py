import pytest
from app import fibonacci

@pytest.mark.parametrize('args,expected',[([7], 13), ([0], 0)])
def test_visible(args,expected):
    assert fibonacci(*args)==expected
