from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.models import User
from app.schemas.master_data import DataQualityRiskAlertPage, DataQualityRiskRulePage
from app.services.data_quality_risk_service import build_data_quality_risk_alerts, list_data_quality_risk_rules


router = APIRouter(prefix="/data-quality", tags=["data-quality"])


@router.get("/risk-alerts", response_model=DataQualityRiskAlertPage)
def list_risk_alerts(
    level: str | None = Query(default=None, pattern="^(warning|risk)$"),
    category: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.view")),
) -> dict:
    return build_data_quality_risk_alerts(
        db,
        level=level,
        category=category,
        limit=limit,
        offset=offset,
    )


@router.get("/risk-rules", response_model=DataQualityRiskRulePage)
def list_risk_rules(
    level: str | None = Query(default=None, pattern="^(warning|risk)$"),
    category: str | None = None,
    resource_type: str | None = None,
    current_user: User = Depends(require_permission("import.view")),
) -> dict:
    return list_data_quality_risk_rules(level=level, category=category, resource_type=resource_type)
