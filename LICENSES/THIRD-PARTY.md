# Third-party licenses

upbox is MIT licensed (see `../LICENSE`). It depends on the following
open-source projects. License texts are linked rather than vendored so
they stay accurate as the upstream evolves; resolve them at the version
pinned in `uv.lock`.

## Runtime dependencies

- **[mitmproxy](https://github.com/mitmproxy/mitmproxy)** — MIT.
  The TLS interception + HTTP proxy core.
- **[FastAPI](https://github.com/tiangolo/fastapi)** — MIT.
  The dashboard HTTP server.
- **[Starlette](https://github.com/encode/starlette)** — BSD-3.
  ASGI primitives (FastAPI dependency).
- **[uvicorn](https://github.com/encode/uvicorn)** — BSD-3.
  ASGI server.
- **[Jinja2](https://github.com/pallets/jinja)** — BSD-3.
  Dashboard templates.
- **[typer](https://github.com/tiangolo/typer)** — MIT.
  CLI framework.
- **[click](https://github.com/pallets/click)** — BSD-3.
  CLI primitives (typer dependency).
- **[PyYAML](https://github.com/yaml/pyyaml)** — MIT.
  Rule file parsing.
- **[cryptography](https://github.com/pyca/cryptography)** — Apache-2.0 / BSD-3.
  CA generation.
- **[python-multipart](https://github.com/Kludex/python-multipart)** — Apache-2.0.
  FastAPI form parsing.

## Build dependencies

- **[hatchling](https://github.com/pypa/hatch)** — MIT.
  Build backend.
- **[uv](https://github.com/astral-sh/uv)** — Apache-2.0 / MIT.
  Package manager.

## Verifying licenses for a specific install

```sh
uv pip list --format=json | python -c '
import json, sys, importlib.metadata
for entry in json.load(sys.stdin):
    name = entry["name"]
    try:
        meta = importlib.metadata.metadata(name)
        print(f"{name}: {meta.get(\"License\", \"unknown\")}")
    except importlib.metadata.PackageNotFoundError:
        pass
'
```
