FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt

# Only the serving code and the batch-prediction artifacts: no raw data, no training stack in the image.
COPY app/ app/
COPY artifacts/predictions.parquet artifacts/item_forecast.parquet artifacts/metadata.json artifacts/

RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
