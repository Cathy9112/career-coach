ARG PYTHON_IMAGE=m.daocloud.io/docker.io/library/python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TIMEOUT=120
ARG APT_MIRROR=https://mirrors.aliyun.com

WORKDIR /app
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i \
            -e "s|http://deb.debian.org|${APT_MIRROR}|g" \
            -e "s|https://deb.debian.org|${APT_MIRROR}|g" \
            /etc/apt/sources.list.d/debian.sources; \
    fi \
    && if [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e "s|http://deb.debian.org|${APT_MIRROR}|g" \
            -e "s|https://deb.debian.org|${APT_MIRROR}|g" \
            /etc/apt/sources.list; \
    fi \
    && apt-get \
        -o Acquire::Retries=5 \
        -o Acquire::http::Timeout=30 \
        -o Acquire::https::Timeout=30 \
        update \
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
