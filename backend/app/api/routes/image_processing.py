from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import SessionLocal, get_db
from app.models import ImageProcessingFile, ImageProcessingJob, User
from app.services.audit_service import write_audit_log


router = APIRouter(prefix="/image-jobs", tags=["image-processing"])

PROJECT_ROOT = Path(__file__).resolve().parents[4]
IMAGE_TOOL_DIR = Path(os.environ.get("PROJECT_BASE_IMAGE_TOOL_DIR", PROJECT_ROOT / "tools" / "image_batch_processor"))
IMAGE_JOB_ROOT = Path(os.environ.get("PROJECT_BASE_IMAGE_JOB_ROOT", PROJECT_ROOT / "runtime" / "image_jobs"))
IMAGE_PROCESSING_MAX_FILES = int(os.environ.get("PROJECT_BASE_IMAGE_PROCESSING_MAX_FILES", "12"))
IMAGE_PROCESSING_MAX_BYTES = int(os.environ.get("PROJECT_BASE_IMAGE_PROCESSING_MAX_BYTES", str(15 * 1024 * 1024)))
IMAGE_PROCESSING_RETENTION_DAYS = int(os.environ.get("PROJECT_BASE_IMAGE_PROCESSING_RETENTION_DAYS", "30"))
IMAGE_PROCESSING_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
IMAGE_PROCESSING_TEMPLATES: dict[str, dict[str, Any]] = {
    "main": {
        "key": "main",
        "label": "主图模板",
        "description": "适合商品主图，输出 636 x 636。",
        "output_width": 636,
        "output_height": 636,
        "output_suffix": "_main",
        "watermark_opacity": 0.68,
    },
    "detail": {
        "key": "detail",
        "label": "详情图模板",
        "description": "适合详情页长图，输出宽 515 x 长 900。",
        "output_width": 515,
        "output_height": 900,
        "output_suffix": "_detail",
        "watermark_opacity": 0.62,
    },
}
ALL_IMAGE_SCOPE_ROLES = {"admin", "boss", "business_middle_office", "data_middle_office"}


def _template(template_type: str | None) -> dict[str, Any]:
    key = (template_type or "main").strip().lower()
    return IMAGE_PROCESSING_TEMPLATES.get(key) or IMAGE_PROCESSING_TEMPLATES["main"]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "on", "yes", "y"}


def _clean_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(number, max_value))


def _clean_float(value: Any, default: float, min_value: float, max_value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(number, max_value))


def _safe_storage_filename(filename: str, fallback_prefix: str = "image") -> str:
    raw_name = os.path.basename(filename or "").strip()
    stem, ext = os.path.splitext(raw_name)
    safe_stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", stem).strip("._-")
    safe_stem = safe_stem[:80] or fallback_prefix
    return f"{safe_stem}{ext.lower()}"


def _safe_watermark_filename(filename: str) -> str:
    safe_name = _safe_storage_filename(filename, "watermark")
    return safe_name if safe_name in {"main_watermark.png", "光效模板.png"} else "main_watermark.png"


def _image_processing_options(
    *,
    template_type: str,
    output_width: int | None,
    output_height: int | None,
    output_format: str,
    jpeg_quality: int | None,
    margin_ratio: float | None,
    background_color: str | None,
    transparent_background: bool,
    output_suffix: str | None,
    watermark_enabled: bool,
    watermark_template: str,
    watermark_position: str,
    watermark_scale_ratio: float | None,
    watermark_opacity: float | None,
    watermark_margin: int | None,
    watermark_blend_mode: str,
) -> dict[str, Any]:
    template = _template(template_type)
    output_format = (output_format or "jpg").strip().lower()
    if output_format not in {"jpg", "jpeg", "png", "webp"}:
        output_format = "jpg"
    background_color = (background_color or "255,255,255").strip()
    if not re.fullmatch(r"\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}", background_color):
        background_color = "255,255,255"
    watermark_position = (watermark_position or "tile").strip()
    if watermark_position not in {"top_left", "top_right", "bottom_left", "bottom_right", "center", "tile"}:
        watermark_position = "tile"
    watermark_blend_mode = (watermark_blend_mode or "normal").strip()
    if watermark_blend_mode not in {"normal", "screen", "multiply", "overlay", "soft_light"}:
        watermark_blend_mode = "normal"
    suffix = (output_suffix or str(template["output_suffix"])).strip()[:30] or str(template["output_suffix"])
    return {
        "template_type": template["key"],
        "output_width": _clean_int(output_width, int(template["output_width"]), 200, 4000),
        "output_height": _clean_int(output_height, int(template["output_height"]), 200, 4000),
        "output_format": output_format,
        "jpeg_quality": _clean_int(jpeg_quality, 95, 50, 100),
        "margin_ratio": _clean_float(margin_ratio, 0.08, 0.0, 0.45),
        "background_color": background_color,
        "transparent_background": transparent_background,
        "output_suffix": suffix,
        "watermark_enabled": watermark_enabled,
        "watermark_template": _safe_watermark_filename(watermark_template),
        "watermark_position": watermark_position,
        "watermark_scale_ratio": _clean_float(watermark_scale_ratio, 0.18, 0.02, 1.0),
        "watermark_opacity": _clean_float(watermark_opacity, float(template["watermark_opacity"]), 0.0, 1.0),
        "watermark_margin": _clean_int(watermark_margin, 80, 0, 800),
        "watermark_blend_mode": watermark_blend_mode,
    }


def _tool_status() -> tuple[bool, str]:
    script_path = IMAGE_TOOL_DIR / "main.py"
    if not script_path.exists():
        return False, f"图片处理脚本未安装：{script_path}"
    watermark_path = IMAGE_TOOL_DIR / "watermarks" / "main_watermark.png"
    if not watermark_path.exists():
        return False, f"主图水印模板缺失：{watermark_path}"
    return True, "ready"


def _create_job_directories(job_no: str) -> dict[str, Path]:
    job_dir = IMAGE_JOB_ROOT / job_no
    paths = {
        "job": job_dir,
        "input": job_dir / "input",
        "output": job_dir / "output",
        "logs": job_dir / "logs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _media_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _image_processing_command(paths: dict[str, Path], options: dict[str, Any]) -> list[str]:
    command = [
        sys.executable,
        str(IMAGE_TOOL_DIR / "main.py"),
        "--json",
        "--quiet",
        "--input-dir",
        str(paths["input"]),
        "--output-dir",
        str(paths["output"]),
        "--watermark-dir",
        str(IMAGE_TOOL_DIR / "watermarks"),
        "--output-width",
        str(options["output_width"]),
        "--output-height",
        str(options["output_height"]),
        "--output-format",
        str(options["output_format"]),
        "--jpeg-quality",
        str(options["jpeg_quality"]),
        "--margin-ratio",
        str(options["margin_ratio"]),
        "--background-color",
        str(options["background_color"]),
        "--output-suffix",
        str(options["output_suffix"]),
        "--log-path",
        str(paths["logs"] / "process.log"),
    ]
    command.append("--transparent-background" if options.get("transparent_background") else "--no-transparent-background")
    if options.get("watermark_enabled"):
        command.extend(
            [
                "--watermark-path",
                str(IMAGE_TOOL_DIR / "watermarks" / str(options["watermark_template"])),
                "--watermark-position",
                str(options["watermark_position"]),
                "--watermark-scale-ratio",
                str(options["watermark_scale_ratio"]),
                "--watermark-opacity",
                str(options["watermark_opacity"]),
                "--watermark-margin",
                str(options["watermark_margin"]),
                "--watermark-blend-mode",
                str(options["watermark_blend_mode"]),
            ]
        )
    return command


def _base_job_query(current_user: User) -> Select[tuple[ImageProcessingJob]]:
    stmt = select(ImageProcessingJob)
    if current_user.role not in ALL_IMAGE_SCOPE_ROLES:
        stmt = stmt.where(ImageProcessingJob.created_by_user_id == current_user.id)
    return stmt


def _job_or_404(db: Session, job_id: int, current_user: User) -> ImageProcessingJob:
    job = db.scalar(_base_job_query(current_user).where(ImageProcessingJob.id == job_id))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片处理任务不存在")
    return job


def _file_or_404(db: Session, job: ImageProcessingJob, file_id: int) -> ImageProcessingFile:
    item = db.scalar(select(ImageProcessingFile).where(ImageProcessingFile.job_id == job.id, ImageProcessingFile.id == file_id))
    if item is None or item.status != "success":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="处理结果不存在")
    if not item.output_path or not Path(item.output_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="处理结果文件不存在")
    return item


def _serialize_job(job: ImageProcessingJob) -> dict[str, Any]:
    return jsonable_encoder(
        {
            "id": job.id,
            "job_no": job.job_no,
            "created_by_user_id": job.created_by_user_id,
            "created_by_username": job.created_by_username,
            "template_type": job.template_type,
            "status": job.status,
            "input_count": job.input_count,
            "success_count": job.success_count,
            "failed_count": job.failed_count,
            "skipped_count": job.skipped_count,
            "options": job.options_json or {},
            "result": job.result_json or {},
            "error_message": job.error_message,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
        }
    )


def _serialize_file(item: ImageProcessingFile) -> dict[str, Any]:
    download_url = f"/api/v1/image-jobs/{item.job_id}/files/{item.id}" if item.status == "success" else None
    preview_url = f"/api/v1/image-jobs/{item.job_id}/files/{item.id}/preview" if item.status == "success" else None
    return jsonable_encoder(
        {
            "id": item.id,
            "job_id": item.job_id,
            "original_filename": item.original_filename,
            "output_filename": item.output_filename,
            "content_type": item.content_type,
            "size_bytes": item.size_bytes,
            "sort_order": item.sort_order,
            "status": item.status,
            "error_message": item.error_message,
            "download_url": download_url,
            "preview_url": preview_url,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
    )


def _cleanup_expired_jobs() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=IMAGE_PROCESSING_RETENTION_DAYS)
    with SessionLocal() as db:
        jobs = list(
            db.scalars(
                select(ImageProcessingJob)
                .where(
                    ImageProcessingJob.created_at < cutoff,
                    ImageProcessingJob.status.in_(["completed", "partial", "failed", "cancelled"]),
                )
                .limit(100)
            ).all()
        )
        for job in jobs:
            shutil.rmtree(IMAGE_JOB_ROOT / job.job_no, ignore_errors=True)
            db.delete(job)
        if jobs:
            db.commit()


def run_image_processing_job(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(ImageProcessingJob, job_id)
        if job is None:
            return
        options = dict(job.options_json or {})
        paths = _create_job_directories(job.job_no)
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.commit()
        try:
            available, message = _tool_status()
            if not available:
                raise RuntimeError(message)
            completed = subprocess.run(
                _image_processing_command(paths, options),
                cwd=IMAGE_TOOL_DIR,
                capture_output=True,
                text=True,
                timeout=20 * 60,
                check=False,
            )
            stdout = completed.stdout.strip()
            stderr = completed.stderr.strip()
            parsed: dict[str, Any] = {}
            if stdout:
                try:
                    parsed = json.loads(stdout)
                except json.JSONDecodeError:
                    parsed = {"status": "error", "raw_stdout": stdout[-4000:]}
            if completed.returncode not in {0, 10}:
                raise RuntimeError(parsed.get("error") or stderr or stdout or f"处理脚本退出码 {completed.returncode}")

            outputs = parsed.get("outputs") or []
            output_by_input = {
                os.path.basename(str(item.get("input") or "")): item
                for item in outputs
                if isinstance(item, dict)
            }
            failures = {
                os.path.basename(str(item.get("input") or "")): str(item.get("error") or "处理失败")
                for item in (parsed.get("failures") or [])
                if isinstance(item, dict)
            }
            success_count = 0
            failed_count = 0
            for file_row in db.scalars(select(ImageProcessingFile).where(ImageProcessingFile.job_id == job_id)).all():
                input_name = os.path.basename(str(file_row.input_path or ""))
                output_item = output_by_input.get(input_name)
                if output_item and output_item.get("output"):
                    output_path = str(output_item["output"])
                    file_row.status = "success"
                    file_row.output_path = output_path
                    file_row.output_filename = os.path.basename(output_path)
                    file_row.error_message = None
                    success_count += 1
                else:
                    file_row.status = "failed"
                    file_row.error_message = failures.get(input_name) or "脚本未返回该文件的输出结果"
                    failed_count += 1

            summary = parsed.get("summary") or {}
            job.success_count = int(summary.get("success") or success_count)
            job.failed_count = int(summary.get("failed") or failed_count)
            job.skipped_count = int(summary.get("skipped") or 0)
            job.status = "completed" if job.failed_count == 0 else ("partial" if job.success_count else "failed")
            job.result_json = parsed
            job.error_message = None
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:
            message = str(exc)[:2000]
            job.status = "failed"
            job.error_message = message
            job.finished_at = datetime.now(timezone.utc)
            for file_row in db.scalars(
                select(ImageProcessingFile).where(ImageProcessingFile.job_id == job_id, ImageProcessingFile.status == "queued")
            ).all():
                file_row.status = "failed"
                file_row.error_message = message
            db.commit()


@router.get("/config")
def image_processing_config(current_user: User = Depends(require_permission("crm_image.view"))) -> dict[str, Any]:
    available, message = _tool_status()
    return {
        "templates": IMAGE_PROCESSING_TEMPLATES,
        "max_files": IMAGE_PROCESSING_MAX_FILES,
        "max_bytes": IMAGE_PROCESSING_MAX_BYTES,
        "retention_days": IMAGE_PROCESSING_RETENTION_DAYS,
        "tool_available": available,
        "tool_status": message,
    }


@router.get("")
def list_image_processing_jobs(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("crm_image.view")),
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 100))
    jobs = list(db.scalars(_base_job_query(current_user).order_by(ImageProcessingJob.created_at.desc()).limit(safe_limit)).all())
    return [_serialize_job(job) for job in jobs]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_image_processing_job(
    request: Request,
    template_type: str = Form("main"),
    output_width: int | None = Form(None),
    output_height: int | None = Form(None),
    output_format: str = Form("jpg"),
    jpeg_quality: int | None = Form(None),
    margin_ratio: float | None = Form(None),
    background_color: str | None = Form("255,255,255"),
    transparent_background: bool = Form(False),
    output_suffix: str | None = Form(None),
    watermark_enabled: bool = Form(True),
    watermark_template: str = Form("main_watermark.png"),
    watermark_position: str = Form("tile"),
    watermark_scale_ratio: float | None = Form(None),
    watermark_opacity: float | None = Form(None),
    watermark_margin: int | None = Form(None),
    watermark_blend_mode: str = Form("normal"),
    images: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("crm_image.process")),
) -> dict[str, Any]:
    available, message = _tool_status()
    if not available:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=message)
    uploads = [upload for upload in images if upload.filename]
    if not uploads:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少上传一张图片")
    if len(uploads) > IMAGE_PROCESSING_MAX_FILES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"一次最多上传 {IMAGE_PROCESSING_MAX_FILES} 张图片")

    options = _image_processing_options(
        template_type=template_type,
        output_width=output_width,
        output_height=output_height,
        output_format=output_format,
        jpeg_quality=jpeg_quality,
        margin_ratio=margin_ratio,
        background_color=background_color,
        transparent_background=transparent_background,
        output_suffix=output_suffix,
        watermark_enabled=watermark_enabled,
        watermark_template=watermark_template,
        watermark_position=watermark_position,
        watermark_scale_ratio=watermark_scale_ratio,
        watermark_opacity=watermark_opacity,
        watermark_margin=watermark_margin,
        watermark_blend_mode=watermark_blend_mode,
    )
    job_no = f"IMG-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"
    paths = _create_job_directories(job_no)
    saved_files: list[dict[str, Any]] = []
    for index, upload in enumerate(uploads, start=1):
        original_name = str(upload.filename or f"image-{index}.jpg")
        ext = os.path.splitext(original_name)[1].lower()
        if ext not in IMAGE_PROCESSING_EXTENSIONS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"不支持的图片格式：{original_name}")
        content = await upload.read()
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"图片为空：{original_name}")
        if len(content) > IMAGE_PROCESSING_MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"单个图片不能超过 {IMAGE_PROCESSING_MAX_BYTES // 1024 // 1024}MB：{original_name}",
            )
        safe_name = f"{index:03d}_{_safe_storage_filename(original_name, 'image')}"
        input_path = paths["input"] / safe_name
        input_path.write_bytes(content)
        saved_files.append(
            {
                "original_filename": original_name,
                "input_path": str(input_path),
                "content_type": upload.content_type,
                "size_bytes": len(content),
                "sort_order": index,
            }
        )

    job = ImageProcessingJob(
        job_no=job_no,
        created_by_user_id=current_user.id,
        created_by_username=current_user.username,
        template_type=str(options["template_type"]),
        status="queued",
        input_count=len(saved_files),
        success_count=0,
        failed_count=0,
        skipped_count=0,
        options_json=options,
        result_json={},
    )
    db.add(job)
    db.flush()
    for item in saved_files:
        db.add(ImageProcessingFile(job_id=job.id, status="queued", **item))
    write_audit_log(
        db,
        action_type="create_image_processing_job",
        resource_type="crm_image",
        resource_id=str(job.id),
        user=current_user,
        request=request,
        after_data={"job_no": job.job_no, "files": len(saved_files), "template_type": job.template_type},
    )
    db.commit()
    threading.Thread(target=run_image_processing_job, args=(job.id,), daemon=True).start()
    return {"job_id": job.id, "job_no": job.job_no, "status": job.status}


@router.get("/{job_id}")
def get_image_processing_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("crm_image.view")),
) -> dict[str, Any]:
    job = _job_or_404(db, job_id, current_user)
    files = list(db.scalars(select(ImageProcessingFile).where(ImageProcessingFile.job_id == job.id).order_by(ImageProcessingFile.sort_order, ImageProcessingFile.id)).all())
    return {
        "job": _serialize_job(job),
        "files": [_serialize_file(item) for item in files],
        "download_all_url": f"/api/v1/image-jobs/{job.id}/download" if any(item.status == "success" for item in files) else None,
    }


@router.get("/{job_id}/files/{file_id}")
def download_image_processing_file(
    job_id: int,
    file_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("crm_image.download")),
) -> FileResponse:
    job = _job_or_404(db, job_id, current_user)
    item = _file_or_404(db, job, file_id)
    write_audit_log(
        db,
        action_type="download_image_processing_file",
        resource_type="crm_image",
        resource_id=str(job.id),
        user=current_user,
        request=request,
        after_data={"file_id": item.id, "filename": item.output_filename},
    )
    db.commit()
    return FileResponse(str(item.output_path), media_type="application/octet-stream", filename=item.output_filename or Path(str(item.output_path)).name)


@router.get("/{job_id}/files/{file_id}/preview")
def preview_image_processing_file(
    job_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("crm_image.view")),
) -> FileResponse:
    job = _job_or_404(db, job_id, current_user)
    item = _file_or_404(db, job, file_id)
    return FileResponse(str(item.output_path), media_type=_media_type(str(item.output_path)))


@router.get("/{job_id}/download")
def download_image_processing_job_zip(
    job_id: int,
    request: Request,
    ids: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("crm_image.download")),
) -> FileResponse:
    job = _job_or_404(db, job_id, current_user)
    selected_ids: set[int] = set()
    if ids:
        for item in ids.split(","):
            try:
                selected_ids.add(int(item))
            except ValueError:
                continue
    stmt = select(ImageProcessingFile).where(ImageProcessingFile.job_id == job.id, ImageProcessingFile.status == "success")
    if selected_ids:
        stmt = stmt.where(ImageProcessingFile.id.in_(selected_ids))
    files = list(db.scalars(stmt.order_by(ImageProcessingFile.sort_order, ImageProcessingFile.id)).all())
    if not files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="暂无可下载结果")
    paths = _create_job_directories(job.job_no)
    zip_path = paths["job"] / f"{job.job_no}_results.zip"
    with ZipFile(zip_path, "w") as archive:
        for item in files:
            if item.output_path and Path(item.output_path).exists():
                archive.write(item.output_path, arcname=item.output_filename or Path(item.output_path).name)
    write_audit_log(
        db,
        action_type="download_image_processing_zip",
        resource_type="crm_image",
        resource_id=str(job.id),
        user=current_user,
        request=request,
        after_data={"job_no": job.job_no, "file_count": len(files), "selected_ids": sorted(selected_ids)},
    )
    db.commit()
    return FileResponse(str(zip_path), media_type="application/zip", filename=f"{job.job_no}_results.zip")


@router.delete("/cleanup-expired")
def cleanup_expired_image_processing_jobs(
    current_user: User = Depends(require_permission("crm_image.process")),
) -> dict[str, str]:
    _cleanup_expired_jobs()
    return {"status": "ok"}
