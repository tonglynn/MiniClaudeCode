import pytest
from app import balanced

@pytest.mark.parametrize('args,expected',[(['([)]'], False), (['a{b[c](d)}'], True)])
def test_visible(args,expected):
    assert balanced(*args)==expected
