import pytest
from app import parse_bool

@pytest.mark.parametrize('args,expected',[(['false'], False), ([' YES '], True)])
def test_visible(args,expected):
    assert parse_bool(*args)==expected
