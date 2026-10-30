import pytest
from app import moving_average

@pytest.mark.parametrize('args,expected',[([[1, 2, 3, 4], 2], [1.5, 2.5, 3.5]), ([[1], 3], [])])
def test_visible(args,expected):
    assert moving_average(*args)==expected
