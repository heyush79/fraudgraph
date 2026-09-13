"""Synthetic user population (LLD §7): each user has a home city, favourite
merchants, log-normal amount parameters, an active-hours window and a device."""
from __future__ import annotations

import random
from dataclasses import dataclass

from .geo import haversine_km


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

# Default population. With 50 tps this is ~9 txns per user per hour, well under the
# engine's hourly limit of 60, so only injected bursts cross the velocity thresholds.
# (500 users at 50 tps would be 360/h each and flag everybody — found on day 1.)
DEFAULT_USERS = 20_000
MIN_CONTACTS, MAX_CONTACTS = 2, 4   # small P2P circles keep the honest graph sparse


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
    contacts: tuple[str, ...] = ()  # userIds this user sends P2P money to


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
    # contacts are assigned once every id exists; they may be reciprocal, never self
    ids = [u.user_id for u in users]
    with_contacts: list[UserProfile] = []
    for u in users:
        k = min(rng.randint(MIN_CONTACTS, MAX_CONTACTS), len(ids) - 1)
        picks: set[str] = set()
        while len(picks) < k:
            c = rng.choice(ids)
            if c != u.user_id:
                picks.add(c)
        with_contacts.append(
            UserProfile(
                user_id=u.user_id, home=u.home, device_id=u.device_id,
                favourite_merchants=u.favourite_merchants, amount_mu=u.amount_mu,
                amount_sigma=u.amount_sigma, active_start_hour=u.active_start_hour,
                active_end_hour=u.active_end_hour, contacts=tuple(sorted(picks)),
            )
        )
    return with_contacts


def far_cities(home: City, min_km: float) -> list[City]:
    """Cities at least `min_km` from `home`; the GeoInjector needs > 1000 km."""
    return [c for c in CITIES if haversine_km(home.lat, home.lon, c.lat, c.lon) >= min_km]
