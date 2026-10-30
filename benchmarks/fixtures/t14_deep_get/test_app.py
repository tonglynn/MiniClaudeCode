import pytest
from app import deep_get

@pytest.mark.parametrize('args,expected',[([{'a': {'b': 0}}, 'a.b', 9], 0), ([{}, 'a.b', 9], 9)])
def test_visible(args,expected):
    assert deep_get(*args)==expected
