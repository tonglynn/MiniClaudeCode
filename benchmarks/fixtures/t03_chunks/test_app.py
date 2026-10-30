import pytest
from app import chunks

@pytest.mark.parametrize('args,expected',[([[1, 2, 3, 4, 5], 2], [[1, 2], [3, 4], [5]]), ([[], 3], [])])
def test_visible(args,expected):
    assert chunks(*args)==expected
