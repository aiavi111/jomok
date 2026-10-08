FROM python:3.12-slim

ENV PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY webapp ./webapp
COPY fonts ./fonts

# /data — постоянный диск Railway (база заказов и готовые книги)
RUN mkdir -p /data
CMD ["python", "-m", "app.main"]
