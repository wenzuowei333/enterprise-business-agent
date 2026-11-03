"""Sanitize reports for CI upload: no raw paths, request bodies, logs or archives."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]

def collect():
    runs=[]
    for name in ["validation.xml","source-validation.xml","postgres-validation.xml","frontend-validation.xml"]:
        file=ROOT/"runtime"/name
        if not file.exists():continue
        tree=ET.parse(file);cases=list(tree.iter("testcase"))
        runs.append({"report":name,"tests":len(cases),"failures":sum(c.find("failure") is not None for c in cases),
            "errors":sum(c.find("error") is not None for c in cases),"skipped":sum(c.find("skipped") is not None for c in cases),
            "duration_seconds":sum(float(s.get("time","0")) for s in tree.iter("testsuite"))})
    result={"test_runs":runs,"mock_only":True,"real_model_evaluation":False}
    browser=ROOT/"runtime/browser/results.json"
    if browser.exists():result["browser"]=json.loads(browser.read_text())["stats"]
    else:
        browser=ROOT/"runtime/browser/verification.json"
        if browser.exists():
            data=json.loads(browser.read_text());result["browser"]={"status":data["status"],"scenarios":len(data["checks"])}
    for name in ["network-policy.json","data-rebuild.json","execution.json"]:
        file=ROOT/"runtime/ci"/name
        if file.exists():result[name[:-5]]=json.loads(file.read_text())
    result["status"]="passed" if result.get("execution",{}).get("status")=="passed" and runs and all(not any(r[k] for k in ["failures","errors","skipped"]) for r in runs) else "failed"
    target=ROOT/"runtime/ci/public";target.mkdir(parents=True,exist_ok=True)
    (target/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    return result

if __name__=="__main__":print(json.dumps(collect(),ensure_ascii=False,indent=2))
