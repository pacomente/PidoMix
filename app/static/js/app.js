async function api(url, options={}) { const r=await fetch(url,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options}); const d=await r.json().catch(()=>({})); if(!r.ok) throw Object.assign(new Error(d.message||d.error||'Error'),{data:d,status:r.status}); return d; }

async function refreshCart() { window.location.reload(); }

document.querySelectorAll('.add').forEach(btn=>btn.addEventListener('click',async()=>{ try { await api('/api/cart/add',{method:'POST',body:JSON.stringify({product_id:Number(btn.dataset.product),quantity:1})}); btn.textContent='✓ Agregado'; setTimeout(()=>btn.textContent='+ Agregar',1000); } catch(e) { if(e.data?.code==='DIFFERENT_STORE' && confirm('Tu carrito contiene productos de otra tienda. ¿Querés vaciarlo y comenzar un nuevo pedido?')) { await api('/api/cart/clear',{method:'POST'}); await api('/api/cart/add',{method:'POST',body:JSON.stringify({product_id:Number(btn.dataset.product),quantity:1})}); btn.textContent='✓ Agregado'; setTimeout(()=>btn.textContent='+ Agregar',1000); } else alert(e.message); }}));

document.querySelectorAll('.cart-update').forEach(btn=>btn.addEventListener('click',async()=>{ try { await api('/api/cart/update',{method:'POST',body:JSON.stringify({product_id:Number(btn.dataset.product),quantity:Number(btn.dataset.quantity)})}); await refreshCart(); } catch(e) { alert(e.message); }}));

document.getElementById('clear-cart')?.addEventListener('click',async()=>{ if(confirm('¿Vaciar el carrito?')) { await api('/api/cart/clear',{method:'POST'}); await refreshCart(); }});

document.getElementById('delivery_method')?.addEventListener('change',(e)=>{ const address=document.getElementById('address'); if(address) address.required=e.target.value==='delivery'; });
