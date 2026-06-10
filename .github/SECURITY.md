# Reporting Vulnerabilities

If you find a problem in this project that should not be discussed in a
public GitHub issue, please email **sean.galloway@outlook.com** with the
details. Please do not open a public issue for the report itself.

We aim to acknowledge new reports within a week.

## Scope

This project is a Python verification library (BFMs, scoreboards, and
testbench helpers) used in simulation. It does not run as a network
service, does not handle user credentials, and is not deployed as a
production system. Reports most relevant to this project are:

- Defects in BFM logic that could cause silent miscompares (i.e., a test
  passes when it should fail).
- Issues in build/install scripts or CI configuration.
- Exposure of any credentials, tokens, or private data in the repo.

Out of scope: simulation-only behavior that has no impact outside the
test environment.

## What to include

- The version of `cocotb-framework` (or the commit SHA).
- The Python and simulator versions you were running.
- A minimal reproducer if one exists.
- Your contact email for follow-up.

## Supported versions

The project follows the latest release on PyPI. Older minor versions
are not patched; please upgrade to the latest before reporting.
