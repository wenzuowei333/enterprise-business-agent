"""Inventory-only adaptation of source recheck and diagnosis creation semantics."""
import secrets
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app import models as m
from app.core.config import settings
from app.services.inventory_agent_service import _anomaly_reasons, _evidence_version
from app.services.workflow_lock import acquire_exception_case_mutation_lock
from app.services.access_control_service import visible_case, require_permission
from app.services.auth_service import audit


def refresh_inventory_case(db,case):
    anomaly=db.get(m.InventoryAnomalyCase,case.inventory_anomaly_case_id)
    snapshot=db.scalar(select(m.InventorySnapshot).where(m.InventorySnapshot.id==anomaly.snapshot_id).with_for_update()) if anomaly else None
    if snapshot is None:
        raise HTTPException(409,detail={'code':'source_missing','message':'缺少库存快照，不能生成诊断依据'})
    batch=db.get(m.ImportBatch,snapshot.batch_id)
    if not batch or batch.status!='committed':
        raise HTTPException(409,detail={'code':'source_uncommitted','message':'来源批次尚未提交，不能用于诊断'})
    reasons=_anomaly_reasons(snapshot)
    if anomaly.reason_code not in reasons:
        case.status='resolved'
        case.resolved_at=datetime.now(timezone.utc)
        anomaly.status='resolved'
        db.add(m.ExceptionEvent(case_id=case.id,event_type='rule_recheck_resolved',to_status='resolved'))
        return False
    version=_evidence_version(snapshot,anomaly.reason_code)
    data={'kind':'inventory_snapshot','rule_code':anomaly.reason_code,'reason_code':anomaly.reason_code,
          'snapshot_id':snapshot.id,'batch_id':snapshot.batch_id,'data_date':snapshot.data_date.isoformat() if snapshot.data_date else None,
          'product':{'code':snapshot.product_code,'name':snapshot.product_name},
          'warehouse':{'name':snapshot.warehouse_name,'scope':snapshot.warehouse_scope},
          'observed':{'stock_qty':str(snapshot.stock_qty) if snapshot.stock_qty is not None else None,
                      'locked_qty':str(snapshot.locked_base_qty) if snapshot.locked_base_qty is not None else None},
          'allowed_root_cause_codes':['source_record_mismatch','insufficient_evidence']}
    existing=db.scalar(select(m.ExceptionEvidence).where(m.ExceptionEvidence.case_id==case.id,m.ExceptionEvidence.evidence_version==version))
    if existing is None:
        db.add(m.ExceptionEvidence(case_id=case.id,evidence_version=version,data_json=data))
    elif existing.data_json != data:
        # A version identifies immutable evidence; do not silently overwrite a stored payload.
        raise HTTPException(409,detail={'code':'evidence_conflict','message':'证据内容与版本不一致，请核对来源'})
    changed=case.evidence_version!=version
    case.evidence_version=version
    anomaly.evidence_version=version
    anomaly.stock_qty=snapshot.stock_qty
    anomaly.locked_qty=snapshot.locked_base_qty
    case.metadata_json={**(case.metadata_json or {}),'warehouse_name':snapshot.warehouse_name,'reason_code':anomaly.reason_code}
    if changed:
        case.status='open'
        db.add(m.ExceptionEvent(case_id=case.id,event_type='evidence_refreshed',detail_json={'evidence_version':version}))
    db.flush()
    return True


def create_diagnosis_job(db,user,case_id,expected_version,scenario='success',force=False):
    require_permission(db,user,'exception.diagnose')
    if not settings.exception_center_enabled or not settings.exception_ai_enabled:
        raise HTTPException(409,detail={'code':'diagnosis_disabled','message':'诊断功能当前已关闭'})
    acquire_exception_case_mutation_lock(db)
    visible_case(db,user,case_id)
    case=db.scalar(select(m.ExceptionCase).where(m.ExceptionCase.id==case_id).with_for_update())
    if case.status in {'resolved','ignored'}:
        raise HTTPException(409,detail={'code':'case_terminal','message':'已结束的案件不能诊断'})
    if not refresh_inventory_case(db,case):
        audit(db,user,'recheck_resolved',case.id);db.commit()
        raise HTTPException(409,detail={'code':'case_resolved','message':'规则复检已通过，不再需要诊断'})
    visible_case(db,user,case_id)  # reauthorize after reading authoritative source
    if case.evidence_version!=expected_version:
        db.commit()
        raise HTTPException(409,detail={'code':'evidence_changed','message':'证据已更新，请刷新后重试'})
    policy=db.scalar(select(m.ExceptionPolicy).where(m.ExceptionPolicy.policy_key=='default'))
    if not policy or not policy.is_enabled or not policy.manual_ai_enabled:
        raise HTTPException(409,detail={'code':'diagnosis_disabled','message':'人工诊断策略未开启'})
    active=db.scalar(select(m.ExceptionDiagnosisJob).where(m.ExceptionDiagnosisJob.case_id==case.id,
        m.ExceptionDiagnosisJob.evidence_version==case.evidence_version,m.ExceptionDiagnosisJob.status.in_(['queued','processing'])))
    if active:
        if active.demo_scenario!=scenario:
            raise HTTPException(409,detail={'code':'active_scenario_conflict','message':'当前证据已有其他演示场景在执行'})
        return active,True
    if not force:
        completed=db.scalar(select(m.ExceptionDiagnosisJob).where(m.ExceptionDiagnosisJob.case_id==case.id,
            m.ExceptionDiagnosisJob.evidence_version==case.evidence_version,m.ExceptionDiagnosisJob.demo_scenario==scenario,
            m.ExceptionDiagnosisJob.status=='completed').order_by(m.ExceptionDiagnosisJob.id.desc()).limit(1))
        if completed: return completed,True
    job=m.ExceptionDiagnosisJob(job_no='DEMO-JOB-'+secrets.token_hex(8),case_id=case.id,
        evidence_version=case.evidence_version,requested_by_user_id=user.id,trigger_type='manual',
        status='queued',available_at=datetime.now(timezone.utc),demo_scenario=scenario)
    db.add(job);db.flush()
    previous=case.status;case.status='processing'
    db.add(m.ExceptionEvent(case_id=case.id,event_type='diagnosis_queued',actor_user_id=user.id,
        from_status=previous,to_status='processing',detail_json={'job_id':job.id,'scenario':scenario,'evidence_version':job.evidence_version}))
    audit(db,user,'diagnosis_requested',case.id,{'job_id':job.id,'scenario':scenario,'evidence_version':job.evidence_version})
    db.commit()
    return job,False
