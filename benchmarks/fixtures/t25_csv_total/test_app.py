import pytest
from app import csv_total

@pytest.mark.parametrize('args,expected',[(['name,amount\na,1.5\nb,2.25\n'], 3.75), (['name,amount\na,\nb,-2\n'], -2.0)])
def test_visible(args,expected):
    assert csv_total(*args)==expected
