"""New deterministic Mock transport through the retained source evidence contracts."""
from datetime import datetime, timezone
import queue
import threading
import time
import uuid
from pydantic import ValidationError
from app.core.config import settings
from app.services.evidence_contract import prepare_exception_evidence, HermesResponseError
from app.services.provider_contract import HermesCallMetadata, HermesStructuredDiagnosis
from demo.provider import validate_mock_output

SCENARIOS={'success','missing_evidence','invalid_schema','unknown_reference','timeout'}


def _mock_response(projected,scenario,cancel,delay=0):
    if cancel.wait(delay):
        raise TimeoutError('Mock transport cancelled')
    if scenario=='timeout':
        cancel.wait(settings.provider_timeout_seconds+1)
        raise TimeoutError('Mock provider simulated timeout')
    blocked=scenario=='missing_evidence'
    result={'root_cause_code':'insufficient_evidence' if blocked else 'source_record_mismatch',
            'summary':'缺少上游凭证，暂不能判断原因。' if blocked else '库存快照命中异常规则，建议人工核对上游记录。',
            'confidence':0.0 if blocked else 0.55,'evidence_refs':[] if blocked else projected.get('canonical_evidence_refs',[])[:2],
            'impact':'当前证据不足以核实影响。' if blocked else '该商品库存记录需要复核，数值以证据快照为准。',
            'recommended_steps':['请补充上游入出库凭证后重新核对。' if blocked else '请人工核对导入批次与入出库凭证。'],
            'missing_evidence':['尚缺上游入出库凭证。'], 'disposition':'blocked' if blocked else 'manual_review'}
    if scenario=='invalid_schema': result['confidence']='very-high'
    if scenario=='unknown_reference': result['evidence_refs']=['snapshot:unavailable']
    return result


def invoke(evidence,scenario,*,request_id=None,delay=0):
    if scenario not in SCENARIOS: raise ValueError('Unknown Mock scenario')
    projected,input_metadata=prepare_exception_evidence(evidence,domain='inventory')
    started=datetime.now(timezone.utc); clock=time.monotonic()
    cancelled=threading.Event(); channel=queue.Queue(maxsize=1)
    def call():
        try: channel.put((True,_mock_response(projected,scenario,cancelled,delay)))
        except Exception as exc: channel.put((False,exc))
    thread=threading.Thread(target=call,daemon=True,name='mock-provider')
    thread.start()
    try:
        valid,raw=channel.get(timeout=settings.provider_timeout_seconds)
    except queue.Empty as exc:
        cancelled.set()
        raise TimeoutError('Mock provider deadline exceeded') from exc
    if not valid: raise raw
    try:
        diagnosis=validate_mock_output(raw,projected)
    except (ValidationError,HermesResponseError) as exc:
        raise HermesResponseError('Mock output failed evidence/Schema validation') from exc
    completed=datetime.now(timezone.utc)
    metadata=HermesCallMetadata(provider_host=None,model='mock-fixed-v1',request_id=request_id or str(uuid.uuid4()),
        started_at=started,completed_at=completed,latency_ms=max(0,int((time.monotonic()-clock)*1000)),attempts=1,
        **input_metadata)
    return HermesStructuredDiagnosis(diagnosis=diagnosis,metadata=metadata)
