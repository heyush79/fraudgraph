from .base import Injector
from .geo import GeoInjector
from .ring import RingInjector
from .velocity import VelocityInjector

__all__ = ["Injector", "VelocityInjector", "RingInjector", "GeoInjector", "REGISTRY"]

# CLI pattern name -> injector class.
REGISTRY: dict[str, type[Injector]] = {
    "velocity": VelocityInjector,
    "ring": RingInjector,
    "geo": GeoInjector,
}
