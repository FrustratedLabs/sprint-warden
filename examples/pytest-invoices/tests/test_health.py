import invoices


def test_module_imports():
    assert invoices.to_cents("0") == 0
