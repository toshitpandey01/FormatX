FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer libreoffice-calc libreoffice-impress \
    openjdk-17-jdk-headless tesseract-ocr tesseract-ocr-eng \
    libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 formatx
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY formatx ./formatx
COPY java ./java
USER formatx
EXPOSE 8000
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=2", "--threads=1", "--timeout=330", "formatx:create_app()"]
