FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/workspace:/workspace/backend
WORKDIR /workspace/backend
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
RUN groupadd --system app && useradd --system --gid app --home /workspace app && chown -R app:app /workspace
COPY --chown=app:app backend/ ./
COPY --chown=app:app demo/ /workspace/demo/
USER app
CMD ["python", "-m", "demo.seed", "--export-only"]
