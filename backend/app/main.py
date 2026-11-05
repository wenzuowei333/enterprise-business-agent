from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes.admin import router as admin_router
from app.api.routes.approvals import router as approvals_router
from app.api.routes.auth import router as auth_router
from app.api.routes.context import router as context_router
from app.api.routes.customer_tagging import router as customer_tagging_router
from app.api.routes.crm_assistant import router as crm_assistant_router
from app.api.routes.crm_leads import operations_router as crm_lead_operations_router, router as crm_leads_router
from app.api.routes.crm_projects import router as crm_projects_router
from app.api.routes.crm_reports import router as crm_reports_router
from app.api.routes.crm_security import router as crm_security_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.data_quality import router as data_quality_router
from app.api.routes.data_quality_risk import router as data_quality_risk_router
from app.api.routes.employees import router as employees_router
from app.api.routes.external_api import external_router, management_router as external_api_management_router
from app.api.routes.external_api_v2 import router as external_v2_router
from app.api.routes.external_api_v2_operations import router as external_v2_operations_router
from app.api.routes.external_api_v2_governance import router as external_v2_governance_router
from app.api.routes.external_api_v2_inventory import router as external_v2_inventory_router
from app.api.routes.exceptions import router as exceptions_router
from app.api.routes.health import router as health_router
from app.api.routes.fulfillment import router as fulfillment_router
from app.api.routes.global_ai_actions import router as global_ai_actions_router
from app.api.routes.ai_chat import router as ai_chat_router
from app.api.routes.ai_remediations import router as ai_remediations_router
from app.api.routes.image_processing import router as image_processing_router
from app.api.routes.imports import router as imports_router
from app.api.routes.inventory_check import router as inventory_check_router
from app.api.routes.inventory_flow import router as inventory_flow_router
from app.api.routes.master_data import router as master_data_router
from app.api.routes.meta import router as meta_router
from app.api.routes.mobile import router as mobile_router
from app.api.routes.mobile_checks import router as mobile_checks_router
from app.api.routes.mobile_data import router as mobile_data_router
from app.api.routes.mobile_tools import router as mobile_tools_router
from app.api.routes.mobile_round4 import router as mobile_round4_router
from app.api.routes.mobile_round5 import router as mobile_round5_router
from app.api.routes.process_data import router as process_data_router
from app.api.routes.receivables import router as receivables_router
from app.api.routes.users import router as users_router
from app.api.routes.work_items import router as work_items_router
from app.api.mobile_errors import install_mobile_error_contract
from app.core.config import settings
from app.web import router as web_router


def create_app() -> FastAPI:
    static_dir = Path(__file__).resolve().parent / "static"
    upload_dir = Path(settings.upload_root)
    if not upload_dir.is_absolute():
        upload_dir = (Path(__file__).resolve().parents[1] / upload_dir).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_mobile_error_contract(app)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(approvals_router, prefix="/api/v1")
    app.include_router(employees_router, prefix="/api/v1")
    app.include_router(external_api_management_router, prefix="/api/v1")
    app.include_router(imports_router, prefix="/api/v1")
    app.include_router(inventory_check_router, prefix="/api/v1")
    app.include_router(inventory_flow_router, prefix="/api/v1")
    app.include_router(image_processing_router, prefix="/api/v1")
    app.include_router(master_data_router, prefix="/api/v1")
    app.include_router(process_data_router, prefix="/api/v1")
    app.include_router(receivables_router, prefix="/api/v1")
    app.include_router(dashboard_router, prefix="/api/v1")
    app.include_router(data_quality_router, prefix="/api/v1")
    app.include_router(data_quality_risk_router, prefix="/api/v1")
    app.include_router(exceptions_router, prefix="/api/v1")
    app.include_router(context_router, prefix="/api/v1")
    app.include_router(customer_tagging_router, prefix="/api/v1")
    app.include_router(fulfillment_router, prefix="/api/v1")
    app.include_router(global_ai_actions_router, prefix="/api/v1")
    app.include_router(ai_chat_router, prefix="/api/v1")
    app.include_router(ai_remediations_router, prefix="/api/v1")
    app.include_router(crm_assistant_router, prefix="/api/v1")
    app.include_router(crm_leads_router, prefix="/api/v1")
    app.include_router(crm_lead_operations_router, prefix="/api/v1")
    app.include_router(crm_projects_router, prefix="/api/v1")
    app.include_router(crm_reports_router, prefix="/api/v1")
    app.include_router(crm_security_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")
    app.include_router(work_items_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(meta_router, prefix="/api/v1")
    app.include_router(mobile_router, prefix="/api/v1")
    app.include_router(mobile_data_router, prefix="/api/v1")
    app.include_router(mobile_checks_router, prefix="/api/v1")
    app.include_router(mobile_tools_router, prefix="/api/v1")
    app.include_router(mobile_round4_router, prefix="/api/v1")
    app.include_router(mobile_round5_router, prefix="/api/v1")
    app.include_router(external_router)
    app.include_router(external_v2_router)
    app.include_router(external_v2_operations_router)
    app.include_router(external_v2_governance_router)
    app.include_router(external_v2_inventory_router)
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
        download_dir = static_dir / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/downloads", StaticFiles(directory=download_dir), name="downloads")
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")
    app.include_router(web_router)

    return app


app = create_app()
