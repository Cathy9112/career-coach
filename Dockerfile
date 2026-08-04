ARG PYTHON_IMAGE=m.daocloud.io/docker.io/library/python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TIMEOUT=120

WORKDIR /app
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
EXPOSE 5200
CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
