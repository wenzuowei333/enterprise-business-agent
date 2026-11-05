"""Exercise the complete application's real API against the isolated Mock stack."""
import argparse
from http.cookiejar import CookieJar
import json
from pathlib import Path
import time
import urllib.request

parser=argparse.ArgumentParser()
parser.add_argument('--base-url',default='http://127.0.0.1:18210')
args=parser.parse_args()
if args.base_url != 'http://127.0.0.1:18210':
    raise SystemExit('Only the dedicated loopback full demo is supported')
client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(CookieJar()))


def request(path,payload=None):
    body=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(args.base_url+path,data=body,headers={'Content-Type':'application/json'})
    with client.open(req,timeout=30) as r:
        return json.loads(r.read())


request('/api/v1/auth/login',{'username':'demo_admin','password':'LocalDemo-2026!'})
scan=request('/api/v1/exceptions/scan?domains=inventory',{})
cases=request('/api/v1/exceptions/page?limit=50')
assert cases['total']>0
case=next(x for x in cases['items'] if x['rule_code']=='inventory.negative_stock')
job=request('/api/v1/exceptions/'+case['case_no']+'/diagnoses',{'force':True})
for _ in range(120):
    result=request('/api/v1/exception-jobs/'+str(job['id']))
    if result['status'] in {'completed','failed','cancelled'}:
        break
    time.sleep(0.5)
assert result['status']=='completed',result
with client.open(args.base_url+'/dashboard',timeout=10) as response:
    assert b'<div id="app"></div>' in response.read()
output={'status':'passed','synthetic':True,'provider':'bundled_local_mock','case_count':cases['total'],
        'inventory_scan':scan['scanned'],'diagnosis_status':result['status'],'frontend_served':True,
        'paid_model_calls':0,'real_model_evaluation':False}
out=Path('runtime');out.mkdir(exist_ok=True)
(out/'full-app-smoke.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(output,ensure_ascii=False))
