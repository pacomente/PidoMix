from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
router=APIRouter()

@router.post('/cart/add')
async def add(request: Request):
    data=await request.json(); pid=int(data['product_id']); qty=max(1,int(data.get('quantity',1)))
    cart=request.session.get('cart',[])
    existing=next((x for x in cart if x['product_id']==pid),None)
    if existing: existing['quantity']+=qty
    else: cart.append({'product_id':pid,'quantity':qty})
    request.session['cart']=cart
    return JSONResponse({'ok':True,'cart_count':sum(x['quantity'] for x in cart)})

@router.get('/cart')
async def get_cart(request: Request): return {'items':request.session.get('cart',[]),'count':sum(x['quantity'] for x in request.session.get('cart',[]))}

@router.post('/cart/clear')
async def clear(request: Request): request.session['cart']=[]; return {'ok':True}
