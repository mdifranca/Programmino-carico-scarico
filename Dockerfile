FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-ita \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

ENV MAGAZZINO_HOST=0.0.0.0
ENV MAGAZZINO_DATA_DIR=/data
ENV PORT=10000

RUN mkdir -p /data

EXPOSE 10000

CMD ["python3", "server.py"]
