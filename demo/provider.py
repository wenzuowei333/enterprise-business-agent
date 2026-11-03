"""New showcase adapter. Fixture generation, not production model evidence."""
from app.services.evidence_contract import ExceptionDiagnosis, HermesResponseError, _assert_safe_recommendations, prepare_exception_evidence


def validate_mock_output(raw, projected):
    result = ExceptionDiagnosis.model_validate(raw)
    if result.root_cause_code not in projected.get("allowed_root_cause_codes", []):
        raise HermesResponseError("Unsupported root cause")
    refs = set(projected.get("canonical_evidence_refs", []))
    if any(ref not in refs for ref in result.evidence_refs):
        raise HermesResponseError("Unknown evidence reference")
    if result.disposition != "blocked" and not result.evidence_refs:
        raise HermesResponseError("Evidence required")
    _assert_safe_recommendations(result)
    return result


def diagnose(evidence, invalid_reference=False):
    projected, metadata = prepare_exception_evidence(evidence, domain="inventory")
    refs = projected.get("canonical_evidence_refs", [])
    result = {"root_cause_code":"insufficient_evidence", "summary":"这是演示替身的结构化诊断，实际原因需人工核实。",
              "confidence":0.5, "evidence_refs": ["snapshot:unavailable"] if invalid_reference else refs[:2],
              "impact":"合成库存快照触发异常规则，请核对来源记录。", "recommended_steps":["请人工核对导入批次与库存凭证。"],
              "missing_evidence":["尚缺少上游库存凭证。"], "disposition":"manual_review" if refs else "blocked"}
    return {"mock":True,"diagnosis":validate_mock_output(result, projected).model_dump(),"input_metadata":metadata}
