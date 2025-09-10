# syntax = docker/dockerfile:1.18

FROM python:3.13-slim-bullseye

ENV DEBIAN_FRONTEND=noninteractive \
    PATH="${PATH}:/root/.local/bin" \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN set -eux && \
    apt-get update && \
    apt-get upgrade -qq --assume-yes && \
    apt-get install -qq --assume-yes build-essential python-dev libpcre3 libpcre3-dev zopfli python3-dev default-libmysqlclient-dev pkg-config && \
    python3 -m pip install --upgrade pip && \
    python3 -m pip install poetry && \
    useradd --home-dir /app/ --create-home --shell /bin/bash uwsgi

WORKDIR /app/

COPY --chown=uwsgi:uwsgi /orgchart/ /app/orgchart/

COPY --chown=uwsgi:uwsgi /org/ /app/org/

COPY --chown=uwsgi:uwsgi /pyproject.toml /poetry.lock /manage.py /app/

RUN set -eux && \
    mkdir --parents /app/static/ && \
    POETRY_VIRTUALENVS_CREATE=false poetry install --only main --no-root --no-interaction --no-ansi && \
    ./manage.py collectstatic --no-input && \
    cd /app/static/ && \
    find . -type f -size +0 | while read file; do \
        filename=$(basename -- "$file"); \
        extension="${filename##*.}"; \
        if [ "$extension" = "css" ] || [ "$extension" = "js" ] || [ "$extension" = "svg" ] || [ "$extension" = "html" ]; then \
          zopfli --gzip -v --i10 "$file"; \
          touch "$file".gz "$file"; \
        elif [ "$extension" = "png" ]; then \
          zopflipng -m -y --lossy_transparent --lossy_8bit --filters=01234mepb --iterations=5 "$file" "$file"; \
        fi; \
    done;

USER uwsgi
