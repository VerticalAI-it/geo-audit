# GEO Audit — immagine container (deploy su Railway / Render / Fly)
# NB: richiede un host a container (NON serverless tipo Vercel) per via del
#     browser headless Chromium.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Librerie di sistema per WeasyPrint (PDF) + font
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      libffi8 shared-mime-info fontconfig fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Chromium + le sue dipendenze di sistema (per il rendering JS)
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 8000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
