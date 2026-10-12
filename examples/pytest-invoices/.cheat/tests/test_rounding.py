from invoices import to_cents


def test_S01_whole_amounts():
    assert to_cents("12") == 1200
