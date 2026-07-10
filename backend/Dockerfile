FROM python:3.12-slim

ARG HTTP_PROXY=http://proxy.otsuka-shokai.co.jp:8080
ARG HTTPS_PROXY=http://proxy.otsuka-shokai.co.jp:8080
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8585"]
