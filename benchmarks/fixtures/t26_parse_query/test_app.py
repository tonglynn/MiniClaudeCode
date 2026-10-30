import pytest
from app import parse_query

@pytest.mark.parametrize('args,expected',[(['q=hello+world&q=a%2Bb&x='], {'q': ['hello world', 'a+b'], 'x': ['']}), ([''], {})])
def test_visible(args,expected):
    assert parse_query(*args)==expected
