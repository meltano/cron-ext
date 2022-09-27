# cron-ext

A Meltano utility extension that provides basic job scheduling via cron.

Using the commands documented below, it can format a Meltano schedule into the format used by cron.

For each schedule, a cron entry will be created that runs the appropriate `meltano` command at the specified times.

For instance, a schedule with the name `daily` that has a cron interval of `0 0 * * *` would produce a cron entry like this:

```
0 0 * * * '/path/to/meltano/project/.meltano/run/cron-ext/daily.sh'
```

By default it will be installed into your crontab, but it can also be output to stdout for custom handling. See [the the `install` command documentation](#install) for more details.

The script `daily.sh` will `cd` into your Meltano project directory, set the `$PATH` environment variable to whatever it was when you ran the `install` command, activate the Python virtual environment you had active when running the `install` command, if any, then run either `meltano run ...` or `meltano elt ...` as appropriate, and pipe the output to `/usr/bin/logger` for later processing.

Environment variables set for the Meltano schedule will be set when cron runs the schedule.

The user whose crontab is used (and by extension, who runs the `meltano run`/`meltano elt` command) is the user who ran `meltano invoke cron install`.

## Installation

Merge the following into your `meltano.yml`:

```yaml
plugins:
  utilities:
  - name: cron
    namespace: cron
    pip_url: git+https://github.com/meltano/cron-ext.git
    executable: cron
    commands:
      describe:
        args: describe
        executable: cron
```

Then run the following:

```sh
meltano add utility cron
```

## Usage

Invoke the `cron-ext` CLI with `meltano invoke`. By default it prints help text.

```sh
meltano invoke cron
```

### `install`

To install the schedule of the active project into your crontab, run:

```sh
meltano invoke cron install
```

This will append a new section to your crontab for `cron-ext`-managed schedules for that project. If a `cron-ext` section already exists for the project, it will be updated with the schedules that are being installed. Installing schedules via `cron-ext` will not interfere with non-`cron-ext`-managed lines in your crontab.

To install a subset of the available schedules, specify them by name:

```sh
meltano invoke cron install schedule_a schedule_b ...
```

If you want to avoid using `crontab`, and instead use some other tool to call the schedules in the cron format, you can make the installation target `stdout`:

```sh
meltano invoke cron install --target=stdout
```

### `list`

The `list` command lists the cron entries installed within the `cron-ext` section of the crontab for the active project.

```sh
meltano invoke cron list
```

### `uninstall`

The `uninstall` command uninstalls `cron-ext`-managed cron entries from your crontab.

```sh
meltano invoke cron uninstall
```

By default it will only uninstall entries for which a schedule with a matching name is found within the active Meltano project. Use the `--all` flag to uninstall all cron entries from the crontab for the active project.

```sh
meltano invoke cron uninstall --all
```

Like the `install` command, it can selectively operate on specific schedules specified by name:

```
meltano invoke cron uninstall schedule_a schedule_b ...
```

## Test

The tests are run within a Docker container to avoid interfering with your installed crontabs.

Run `docker-compose -f tests/compose.yml run pytest` to run the tests.

If dependencies in `pyproject.toml` or `poetry.lock` have been updated, run `docker-compose -f tests/compose.yml build`.
