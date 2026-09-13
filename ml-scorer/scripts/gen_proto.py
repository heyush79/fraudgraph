"""Generate scorer/gen/scoring_pb2*.py from the shared proto/scoring.proto.

Run by `make proto`, the Dockerfile, and tests/conftest.py (idempotent). The proto at the
repo root is the single source of truth for the feature vector; nothing here is hand-edited.
"""
from __future__ import annotations

import pathlib
import re
import sys

from grpc_tools import protoc

HERE = pathlib.Path(__file__).resolve().parent.parent          # ml-scorer/
PROTO_DIR = HERE.parent / "proto"
OUT = HERE / "scorer" / "gen"


def generate(proto_dir: pathlib.Path = PROTO_DIR, out: pathlib.Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "__init__.py").touch()
    args = [
        "protoc",
        f"-I{proto_dir}",
        f"--python_out={out}",
        f"--pyi_out={out}",
        f"--grpc_python_out={out}",
        str(proto_dir / "scoring.proto"),
    ]
    if protoc.main(args) != 0:
        sys.exit("protoc failed")
    # grpc's generator emits a top-level `import scoring_pb2`; make it package-relative
    grpc_file = out / "scoring_pb2_grpc.py"
    src = grpc_file.read_text()
    src = re.sub(r"^import scoring_pb2 as", "from . import scoring_pb2 as", src, flags=re.M)
    grpc_file.write_text(src)


if __name__ == "__main__":
    generate()
    print(f"generated into {OUT}")
