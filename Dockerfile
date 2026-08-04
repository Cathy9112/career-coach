ARG PYTHON_IMAGE=m.daocloud.io/docker.io/library/python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TIMEOUT=120

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock ./requirements.lock
RUN pip install \
    --no-cache-dir \
    --require-hashes \
    --index-url "${PIP_INDEX_URL}" \
    --timeout "${PIP_TIMEOUT}" \
    --retries 10 \
    -r requirements.lock
COPY backend/ ./

ENV APP_ENV=production
ENV RESUME_PDF_FONT_PATH=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
EXPOSE 5200
CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
