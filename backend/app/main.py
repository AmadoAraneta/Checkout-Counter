from datetime import datetime, timezone, timedelta
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app=FastAPI(title='Checkout Counter Demo API')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],allow_methods=['*'],allow_headers=['*'])
CARTS={'DEMO-1001':{'cart_id':'CART-1001','session_id':'DEMO-1001','items':[{'product_id':'P-001','product_name':'Arabica Coffee Beans','quantity':1,'unit_price':12.50,'line_total':12.50},{'product_id':'P-002','product_name':'Ceramic Travel Mug','quantity':2,'unit_price':8.75,'line_total':17.50},{'product_id':'P-003','product_name':'Reusable Tote Bag','quantity':1,'unit_price':4.00,'line_total':4.00}],'total':34.0},'DEMO-1002':{'cart_id':'CART-1002','session_id':'DEMO-1002','items':[{'product_id':'P-010','product_name':'Wireless Keyboard','quantity':1,'unit_price':45.0,'line_total':45.0}],'total':45.0}}
PAYMENTS={}; TRANSACTIONS=[]; AUDITS=[]
def now(): return datetime.now(timezone.utc)
def uid(prefix): return f'{prefix}-{uuid4().hex[:10].upper()}'
class PaymentRequest(BaseModel): session_id:str; payment_method:str; amount:float=Field(gt=0)
def cart_or_404(s):
    if s.upper() not in CARTS: raise HTTPException(404,'Cart session not found. Try DEMO-1001.')
    return CARTS[s.upper()]
def status_response(p):
    if p['status']=='waiting' and now()>p['expires_at']: p['status']='expired'
    messages={'waiting':'Waiting for simulated payment','successful':'Payment successful','failed':'Payment failed','expired':'Payment expired'}
    return {'payment_token':p['payment_token'],'status':p['status'],'amount':p['amount'],'method':p['method'],'message':messages[p['status']]}
@app.get('/')
def root(): return {'name':'Checkout Counter Demo API','docs':'/docs','demo_sessions':['DEMO-1001','DEMO-1002']}
@app.get('/api/health')
def health(): return {'status':'ok','demo_mode':True}
@app.get('/api/carts/{session_id}')
def get_cart(session_id): return cart_or_404(session_id)
@app.post('/api/payments')
def create_payment(x:PaymentRequest):
    c=cart_or_404(x.session_id)
    if abs(c['total']-x.amount)>.01: raise HTTPException(422,'Payment amount does not match cart total.')
    t=uid('PAY'); created=now(); p={'payment_token':t,'session_id':c['session_id'],'amount':x.amount,'method':x.payment_method,'status':'waiting','created_at':created,'expires_at':created+timedelta(minutes=5),'mock_url':f'http://localhost:5000/mock-payment/{t}'}; PAYMENTS[t]=p; return p
@app.get('/api/payments/{token}')
def payment_status(token):
    if token not in PAYMENTS: raise HTTPException(404,'Payment token not found.')
    return status_response(PAYMENTS[token])
def finish(token,state):
    if token not in PAYMENTS: raise HTTPException(404,'Payment token not found.')
    p=PAYMENTS[token]
    if p['status']=='waiting':
        p['status']=state
        if state=='successful':
            c=cart_or_404(p['session_id']); tx={'transaction_id':uid('TXN'),'cart_id':c['cart_id'],'session_id':c['session_id'],'amount':p['amount'],'payment_method':p['method'],'timestamp':now(),'payment_status':'successful','items':c['items']}; TRANSACTIONS.append(tx); AUDITS.extend([{'event_id':uid('AUD'),'transaction_id':tx['transaction_id'],'event_type':'PAYMENT_SUCCESS','message':f"Simulated {p['method']} payment completed",'timestamp':now()},{'event_id':uid('AUD'),'transaction_id':tx['transaction_id'],'event_type':'RECEIPT_CREATED','message':'Receipt generated for checkout','timestamp':now()}])
    return status_response(p)
@app.post('/api/payments/{token}/complete')
def complete(token): return finish(token,'successful')
@app.post('/api/payments/{token}/fail')
def fail(token): return finish(token,'failed')
@app.get('/api/transactions')
def transactions(): return list(reversed(TRANSACTIONS))
@app.get('/api/transactions/{tid}/audit')
def audit(tid): return [a for a in AUDITS if a['transaction_id']==tid]
@app.get('/mock-payment/{token}',response_class=HTMLResponse)
def mock_page(token):
    return """<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'><title>Demo Payment</title><style>body{font-family:Arial;max-width:460px;margin:30px auto;padding:20px;background:#f4f7fb}.card{background:#fff;padding:26px;border-radius:16px;box-shadow:0 8px 24px #ccd}button{width:100%;padding:15px;margin-top:12px;border:0;border-radius:10px;font-size:16px}.ok{background:#13795b;color:#fff}.bad{background:#b42318;color:#fff}pre{white-space:pre-wrap}</style><div class='card'><h1>Checkout Demo</h1><p><b>SIMULATION ONLY</b> — no real money is processed.</p><pre>"""+token+"""</pre><button class='ok' onclick=finish('/complete')>Approve simulated payment</button><button class='bad' onclick=finish('/fail')>Fail simulated payment</button><pre id='out'></pre></div><script>async function finish(p){let r=await fetch('/api/payments/"""+token+"""'+p,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});out.textContent=await r.text()}</script>"""
