# ⚠️ 빌드 컨텍스트는 리포지토리 루트여야 한다 (cleanup_temp_images.py가 사용하는 /scripts를
# 함께 담기 위해). 예: docker build -f image-processing-service/Dockerfile -t image-processing-service:latest .
FROM python:3.12-slim AS builder

WORKDIR /app
COPY image-processing-service/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim

WORKDIR /app
RUN useradd --create-home --uid 1000 appuser

COPY --from=builder /root/.local /home/appuser/.local
COPY image-processing-service/ ./
COPY scripts/ ./scripts/

RUN chown -R appuser:appuser /app

USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH

CMD ["python", "main.py"]
