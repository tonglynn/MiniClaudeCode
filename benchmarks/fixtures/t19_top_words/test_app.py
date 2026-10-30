import pytest
from app import top_words

@pytest.mark.parametrize('args,expected',[([['z', 'a', 'z', 'b', 'a', 'z'], 2], ['z', 'a']), ([['b', 'a'], 2], ['a', 'b'])])
def test_visible(args,expected):
    assert top_words(*args)==expected
