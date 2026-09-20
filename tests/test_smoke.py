from decimal import Decimal
from app.services.whatsapp import build_message, normalize_number

def test_normalize_whatsapp():
    assert normalize_number("+54 9 291 123-4567") == "5492911234567"

def test_whatsapp_message():
    class Store: name='Burger Mix'
    msg=build_message(Store(),{'first_name':'Juan','last_name':'Pérez','phone':'123','address':'Calle 1','reference':'Portón rojo','notes':'Sin cebolla'},[{'name':'Burger','unit_price':Decimal('1000'),'quantity':2}],Decimal('2000'),Decimal('500'),Decimal('2500'),'Delivery')
    assert 'Burger Mix' in msg and 'TOTAL: $2,500.00' in msg
