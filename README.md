# cron-ext

A Meltano utility extension that provides basic job scheduling via CRON


## Test

The tests are run within a Docker container to avoid interfering with your installed crontabs.

Run `docker-compose -f tests/compose.yml run pytest` to run the tests.

If dependencies in `pyproject.toml` or `poetry.lock` have been updated, run `docker-compose -f tests/compose.yml build`.
