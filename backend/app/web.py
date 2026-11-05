from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response


BASE_DIR = Path(__file__).resolve().parent
REACT_INDEX = BASE_DIR / "static" / "react" / "index.html"
WEB_TOKEN_COOKIE = "project_base_token"

router = APIRouter(include_in_schema=False)


def react_app() -> FileResponse:
    return FileResponse(REACT_INDEX)


@router.get("/")
@router.get("/login")
@router.get("/dashboard")
@router.get("/imports")
@router.get("/master-data")
@router.get("/sales")
@router.get("/inventory")
@router.get("/purchase")
@router.get("/account-balance")
@router.get("/image-tools")
@router.get("/exceptions")
@router.get("/crm")
@router.get("/crm/{subpath:path}")
@router.get("/crm-projects")
@router.get("/authority")
@router.get("/users")
@router.get("/users/{subpath:path}")
@router.get("/settings")
def spa_entry(subpath: str | None = None) -> FileResponse:
    return react_app()


@router.get("/logout")
def logout_page(request: Request) -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(WEB_TOKEN_COOKIE)
    return response
