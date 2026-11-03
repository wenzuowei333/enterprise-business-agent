FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/workspace:/workspace/backend
WORKDIR /workspace/backend
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ ./
COPY demo/ /workspace/demo/
CMD ["python", "-m", "demo.seed", "--export-only"]
