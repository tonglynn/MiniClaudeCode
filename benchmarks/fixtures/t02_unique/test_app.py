import pytest
from app import unique

@pytest.mark.parametrize('args,expected',[([[3, 1, 3, 2]], [3, 1, 2]), ([[]], [])])
def test_visible(args,expected):
    assert unique(*args)==expected
