"""Actual local browser/API/independent-Worker checks; all data is synthetic."""
import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:18130')
    args=parser.parse_args()
    target=urlparse(args.url)
    if target.hostname not in {'127.0.0.1','localhost'} or target.port not in {18130,18150}:
        raise SystemExit('Browser checks only target this local showcase on port 18130')
    folder=ROOT/'runtime/browser';folder.mkdir(parents=True,exist_ok=True)
    denied=[]
    results=[];errors=[]
    with sync_playwright() as p:
        chrome=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        browser=p.chromium.launch(executable_path=str(chrome) if chrome.exists() else None,headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1100},device_scale_factor=1)
        def route_local(route):
            parsed=urlparse(route.request.url)
            if parsed.scheme in {'data','blob','about'} or (parsed.hostname in {'127.0.0.1','localhost'} and parsed.port==target.port):
                route.continue_()
            else:
                denied.append(parsed.hostname);route.abort()
        context.route('**/*',route_local)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url);expect(page.locator('body')).to_have_attribute('data-ready','true')
        def sign_in(name,count):
            page.select_option('#account',name)
            page.click('#login')
            expect(page.locator('#who')).to_have_text(f'已登录：{name}')
            expect(page.locator('#count')).to_have_text(str(count))
        def submit(scenario,expected_status):
            page.select_option('#scenario',scenario)
            with page.expect_response(lambda r:r.url.endswith('/api/cases/1/diagnose') and r.request.method=='POST') as response:
                page.click('#diagnose')
            payload=response.value.json();assert response.value.status==200,payload
            job=payload['job'];deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                current=context.request.get(f"{args.url}/api/jobs/{job['id']}").json()['job']
                if current['status']==expected_status:break
                time.sleep(0.1)
            else:raise AssertionError(current)
            expect(page.locator('#jobs .job').first).to_contain_text(job['job_no'])
            expect(page.locator('#jobs .job').first).to_contain_text('已完成' if expected_status=='completed' else '失败')
            results.append({'scenario':scenario,'job_id':job['id'],'status':current['status'],'generation':current['generation']})
        sign_in('demo_admin',6)
        page.locator('.case-button').first.click()
        expect(page.locator('#case-summary')).to_contain_text('DEMO-CASE-001')
        submit('success','completed')
        expect(page.locator('#result')).to_contain_text('库存快照命中异常规则')
        assert page.locator('#result code').count()>=1
        page.screenshot(path=str(folder/'admin-success.png'),full_page=True)
        submit('missing_evidence','completed')
        expect(page.locator('#result')).to_contain_text('缺少上游凭证，暂不能判断原因')
        assert page.locator('#result code').count()==0
        page.screenshot(path=str(folder/'insufficient-evidence.png'),full_page=True)
        submit('unknown_reference','failed')
        expect(page.locator('#jobs .job').first).to_contain_text('invalid_provider_output')
        sign_in('demo_viewer',4)
        assert page.locator('#result code').count()==0
        page.locator('.case-button').first.click()
        expect(page.locator('#case-summary')).to_contain_text('DEMO-CASE-001')
        expect(page.locator('#diagnose')).to_be_disabled()
        expect(page.locator('#recheck')).to_be_disabled()
        assert context.request.get(args.url+'/api/cases/5').status==404
        page.screenshot(path=str(folder/'read-only-scope.png'),full_page=True)
        results.append({'scenario':'read_only_and_out_of_scope','visible_cases':4,'west_case_status':404,'buttons_disabled':True})
        sign_in('demo_east',4)
        expect(page.locator('#result')).to_contain_text('尚无诊断结果')
        # Hold the case-list request until logout completes. Its late 401 must
        # not reject an uncaught click handler or overwrite the new identity.
        pending=[]
        page.route('**/api/cases',lambda route:pending.append(route))
        page.locator('.case-button').first.click()
        expect(page.locator('#diagnose')).to_be_enabled()
        page.click('#logout')
        expect(page.locator('#who')).to_have_text('尚未登录')
        assert len(pending)==1
        with page.expect_response(lambda r:r.url.endswith('/api/cases') and r.status==401):
            pending[0].continue_()
        page.unroute('**/api/cases')
        assert page.locator('.case-button').count()==0
        expect(page.locator('#result')).to_contain_text('尚无诊断结果')
        expect(page.locator('#notice')).to_contain_text('已退出')
        results.append({'scenario':'identity_switch_and_logout','previous_case_cache_cleared':True,'late_case_request_after_logout':401})
        page.set_viewport_size({'width':390,'height':844})
        sign_in('demo_admin',6)
        page.locator('.case-button').first.click()
        expect(page.locator('#case-summary')).to_contain_text('DEMO-CASE-001')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
        page.screenshot(path=str(folder/'mobile.png'),full_page=True)
        assert not errors,errors
        assert not denied,denied
        results.append({'scenario':'mobile_layout','width':390,'horizontal_overflow':False,'uncaught_js_errors':errors})
        context.close();browser.close()
    report={'status':'passed','base_url':args.url,'actual_browser':True,'independent_worker':True,'checks':results}
    (folder/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
