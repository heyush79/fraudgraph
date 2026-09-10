"""Synthetic user population (LLD §7): each user has a home city, favourite
merchants, log-normal amount parameters, an active-hours window and a device."""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class City:
    name: str
    lat: float
    lon: float


# Indian metros; distances between them are all > 100 km, most > 1000 km,
# which is what the GeoInjector (Phase 2) needs.
CITIES: tuple[City, ...] = (
    City("Hyderabad", 17.3850, 78.4867),
    City("Mumbai", 19.0760, 72.8777),
    City("Delhi", 28.6139, 77.2090),
    City("Bengaluru", 12.9716, 77.5946),
    City("Chennai", 13.0827, 80.2707),
    City("Kolkata", 22.5726, 88.3639),
    City("Pune", 18.5204, 73.8567),
    City("Ahmedabad", 23.0225, 72.5714),
)

# Merchant categories; the stream engine maps these to a static risk tier.
MERCHANT_CATEGORIES: tuple[str, ...] = (
    "GROC", "FOOD", "FUEL", "RETAIL", "PHARM", "TRAVEL", "ELEC", "GIFT", "CRYPTO", "GAMBLING",
)
MERCHANTS_PER_CATEGORY = 50


def all_merchants() -> list[str]:
    return [f"m_{cat}_{i:04d}" for cat in MERCHANT_CATEGORIES for i in range(MERCHANTS_PER_CATEGORY)]


@dataclass(frozen=True, slots=True)
class UserProfile:
    user_id: str
    home: City
    device_id: str
    favourite_merchants: tuple[str, ...]
    amount_mu: float      # log-normal parameters of the typical spend
    amount_sigma: float
    active_start_hour: int  # UTC hour; users transact mostly inside [start, end)
    active_end_hour: int


def build_population(n_users: int, seed: int) -> list[UserProfile]:
    """Deterministic for a given seed so tests and demos are reproducible."""
    rng = random.Random(seed)
    merchants = all_merchants()
    users: list[UserProfile] = []
    for i in range(n_users):
        home = rng.choice(CITIES)
        favs = tuple(rng.sample(merchants, k=rng.randint(3, 8)))
        # median spend between ~₹150 and ~₹3000, moderately heavy tail
        mu = rng.uniform(5.0, 8.0)
        sigma = rng.uniform(0.5, 0.9)
        start = rng.randint(0, 20)
        end = min(24, start + rng.randint(6, 14))
        users.append(
            UserProfile(
                user_id=f"u_{10000 + i}",
                home=home,
                device_id=f"d_{rng.getrandbits(32):08x}",
                favourite_merchants=favs,
                amount_mu=mu,
                amount_sigma=sigma,
                active_start_hour=start,
                active_end_hour=end,
            )
        )
    return users
