import pytest
from invoices import add_vat


def test_S02_adds_standard_vat():
    assert add_vat(1000, "0.20") == 1200


@pytest.mark.parametrize(("cents", "expected"), [(1, 1), (3, 4), (5, 6)])
def test_S02_vat_rounds_half_up(cents, expected):
    assert add_vat(cents, "0.20") == expected
