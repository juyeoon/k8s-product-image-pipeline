# ⚠️ 빌드 컨텍스트는 리포지토리 루트여야 한다 (run_migration.py가 사용하는 /migrations를
# 함께 담기 위해). 예: docker build -f product-service/Dockerfile -t product-service:latest .
FROM python:3.12-slim AS builder

WORKDIR /app
COPY product-service/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim

WORKDIR /app
RUN useradd --create-home --uid 1000 appuser

COPY --from=builder /root/.local /home/appuser/.local
COPY product-service/ ./
COPY migrations/ ./migrations/

RUN chown -R appuser:appuser /app

USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
