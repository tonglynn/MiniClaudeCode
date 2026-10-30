import pytest
from app import median

@pytest.mark.parametrize('args,expected',[([[8, 2, 4]], 4), ([[4, 1, 3, 2]], 2.5)])
def test_visible(args,expected):
    assert median(*args)==expected
