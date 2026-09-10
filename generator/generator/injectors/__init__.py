from .base import Injector
from .velocity import VelocityInjector

__all__ = ["Injector", "VelocityInjector", "REGISTRY"]

# CLI pattern name -> injector class. Ring and geo land in Phase 2.
REGISTRY: dict[str, type[Injector]] = {
    "velocity": VelocityInjector,
}
