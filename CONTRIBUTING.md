# Contributing to this package

Let's build together! Please see our [Contributor Guide](https://docs.meltano.com/contribute/)
for more information on contributing to this Meltano project.

We believe that everyone can contribute and we welcome all contributions.

Chat with us in [#contributing](https://meltano.slack.com/archives/C013Z450LCD) on [Slack](https://meltano.com/slack).

Contributors are expected to follow our [Code of Conduct](https://docs.meltano.com/contribute/#code-of-conduct).

## Semantic Pull Requests

This repo uses the [semantic-prs](https://github.com/Ezard/semantic-prs) GitHub app to check all PRs against the conventional commit syntax.

Pull requests should be named according to the conventional commit syntax to streamline changelog and release notes management. We encourage (but do not require) the use of conventional commits in commit messages as well.

In general, PR titles should follow the format "<type>: <desc>", where type is any one of these:

- `ci`
- `chore`
- `build`
- `docs`
- `feat`
- `fix`
- `perf`
- `refactor`
- `revert`
- `style`
- `test`

More advanced rules and settings can be found within the file [`.github/semantic.yml`](https://github.com/meltano/basic-python-template/blob/main/.github/semantic.yml).

## Workspace Development Strategies for Meltano Python packages

### pre-commit

We use [pre-commit](https://pre-commit.com/) to install and run linters and similar tools within their own virtual environments. This keeps our dev-dependencies light, which helps avoid dependency conflicts, and maximizes the range of dependencies our packages are compatible with.

`pre-commit` is included as a dev-dependency in our projects. Once installed, it can be used by running `pre-commit` in a shell in the Python environment. By default it will only run on files that have been staged into the git index. It can be run on all files by running `pre-commit run --all-files`. Specific tools (e.g. `mypy`, or `flake8`) can be run individually by supplying their name as an argument, e.g. `pre-commit run mypy`.

To configure `pre-commit`, edit `.pre-commit-config.yaml`.

### Universal Code Formatting

- From the [Black](https://black.readthedocs.io) website:
    > By using Black, you agree to cede control over minutiae of hand-formatting. In return, Black gives you speed, determinism, and freedom from pycodestyle nagging about formatting. You will save time and mental energy for more important matters. **Black makes code review faster by producing the smallest diffs possible.** Blackened code looks the same regardless of the project you’re reading. **Formatting becomes transparent after a while and you can focus on the content instead.**

### Pervasive Python Type Hints

Type hints allow us to spend less time reading documentation. This repo template ships with a default mypy config, it can be relaxed *if* needed on a per-module/per-import basis.

### Docstring convention

All public modules in the Meltano python packages are checked for the presence of docstrings in classes and functions. We follow the [Google Style convention](https://www.sphinx-doc.org/en/master/usage/extensions/example_google.html) for Python docstrings so functions are required to have a description of every argument and the return value, if applicable.
