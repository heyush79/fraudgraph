from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    grpc_port: int = int(os.environ.get("SCORER_GRPC_PORT", "50051"))
    admin_port: int = int(os.environ.get("SCORER_ADMIN_PORT", "8000"))
    registry: pathlib.Path = pathlib.Path(os.environ.get("SCORER_REGISTRY", "registry"))
    workers: int = int(os.environ.get("SCORER_WORKERS", "4"))
    # LLD §4.4: scores that will be ALLOW anyway don't need explanations; 0.4 leaves
    # margin under the 0.60 review threshold so every REVIEW/BLOCK is explained.
    shap_min_probability: float = float(os.environ.get("SCORER_SHAP_MIN_PROB", "0.4"))
