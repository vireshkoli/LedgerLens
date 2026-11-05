# LedgerLens

[![CI](https://github.com/vireshkoli/LedgerLens/actions/workflows/ci.yml/badge.svg)](https://github.com/vireshkoli/LedgerLens/actions/workflows/ci.yml)

An analyst-grade research engine over public company filings. It answers multi-hop questions with citations down to the page and the table cell, and checks every number it shows against official XBRL data.

**Status:** early build. No results exist yet, so none are reported here. Every number that appears in this README later will link to a recorded run.

## Getting started

You need [uv](https://docs.astral.sh/uv/), Node, Docker with Compose and Buildx, and `make` for the shortcuts below. On a Mac, [Colima](https://github.com/abiosoft/colima) runs Docker, and `make dev` starts it with a 6 GiB limit.

```bash
make setup   # install dependencies and git hooks
make lint    # run every check
make test    # run the tests with the coverage gate
make dev     # start the local stack with hot reload
make up      # start the local stack from production images
make down    # stop the local stack and keep its data
make wipe    # stop the local stack and delete its data
make test-stack  # test the running stack
```

The web app is at <http://localhost:5173> and the API docs are at <http://localhost:8000/docs>. Add `COMPOSE_PROFILES=auth,dashboards` to `make dev` or `make up` to include Keycloak, Prometheus and Grafana.

## Data and licences

This repository holds code only. Filings and evaluation datasets are downloaded by scripts and are never committed, and a pre-commit hook and a CI check enforce that.

## Licence

Code is under the [MIT License](LICENSE). Data sources have their own terms.
