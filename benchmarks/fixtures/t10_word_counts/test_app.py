import pytest
from app import word_counts

@pytest.mark.parametrize('args,expected',[(['Hello, HELLO world!'], {'hello': 2, 'world': 1}), ([''], {})])
def test_visible(args,expected):
    assert word_counts(*args)==expected
