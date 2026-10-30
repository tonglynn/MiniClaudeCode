import pytest
from app import slugify

@pytest.mark.parametrize('args,expected',[(['  Hello, WORLD!  '], 'hello-world'), (['A___B'], 'a-b')])
def test_visible(args,expected):
    assert slugify(*args)==expected
