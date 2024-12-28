ARG PYTHON_VERSION=3.13
FROM python:${PYTHON_VERSION}-slim

WORKDIR /cron-ext

RUN apt-get update && \
    apt-get install -y cron git && \
    rm -rf /var/cache/apt/archives /var/lib/apt/lists/* && \
    pip install --upgrade pip && \
    pip install poetry==1.8.5 && \
    poetry --version

COPY pyproject.toml poetry.lock /cron-ext/

RUN poetry install

ENTRYPOINT ["poetry", "run", "pytest"]
