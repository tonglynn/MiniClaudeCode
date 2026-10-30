import pytest
from app import json_lines

@pytest.mark.parametrize('args,expected',[(['{"x":1}\n\n{"x":2}\n'], [{'x': 1}, {'x': 2}]), ([' \n'], [])])
def test_visible(args,expected):
    assert json_lines(*args)==expected
