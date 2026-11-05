# LedgerLens

An analyst-grade research engine over public company filings. It answers multi-hop questions with citations down to the page and the table cell, and checks every number it shows against official XBRL data.

**Status:** early build. No results exist yet, so none are reported here. Every number that appears in this README later will link to a recorded run.

## Getting started

You need [uv](https://docs.astral.sh/uv/), and `make` for the shortcuts below.

```bash
make setup   # install dependencies and git hooks
make lint    # run every check
make test    # run the tests with the coverage gate
```

## Data and licences

This repository holds code only. Filings and evaluation datasets are downloaded by scripts and are never committed, and a pre-commit hook and a CI check enforce that.

## Licence

Code is under the [MIT License](LICENSE). Data sources have their own terms.
