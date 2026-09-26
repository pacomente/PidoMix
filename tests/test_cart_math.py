from decimal import Decimal

def test_total_math():
    subtotal = Decimal('12000')
    shipping = Decimal('1500')
    assert subtotal + shipping == Decimal('13500')
