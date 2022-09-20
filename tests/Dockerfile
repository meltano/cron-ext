FROM python:3.9-slim

WORKDIR /cron-ext

RUN apt-get update && \
    apt-get install -y cron git && \
    rm -rf /var/cache/apt/archives /var/lib/apt/lists/* && \
    pip install --upgrade pip && \
    pip install poetry==1.2.0 && \
    poetry --version

COPY pyproject.toml poetry.lock /cron-ext/

RUN poetry install

ENTRYPOINT ["poetry", "run", "pytest"]
