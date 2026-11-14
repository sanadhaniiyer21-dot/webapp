"""
Weather service and tea recommendation integration.

Uses Open-Meteo (no API key required) with EXTERNAL_API_TIMEOUT.
Maps conditions into:
  - hot (>= 28 C)
  - cold (<= 15 C)
  - rainy (precipitation > 0 or rain weather codes)
  - mild (otherwise)

Provides:
  - get_weather_tea(lat, lon) for GET /api/weather-tea/?lat=&lon=
  - for_city(city) for the home page and /api/weather/
  - last_status() for the health page
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from django.conf import settings
from django.core.cache import cache

from core.errors import SITE_WEATHER_SLOW

log = logging.getLogger("maison")

ENDPOINT = "https://api.open-meteo.com/v1/forecast"
WEATHER_TEA_CACHE_SECONDS = 15 * 60  # 15 minutes
CITY_CACHE_SECONDS = 30 * 60

DEFAULT_CITY = "Coimbatore"

CITIES: dict[str, tuple[float, float]] = {
    "Coimbatore": (11.0168, 76.9558),
    "Chennai": (13.0827, 80.2707),
    "Bengaluru": (12.9716, 77.5946),
    "Mumbai": (19.0760, 72.8777),
    "Delhi": (28.6139, 77.2090),
    "Kolkata": (22.5726, 88.3639),
    "Hyderabad": (17.3850, 78.4867),
    "Kochi": (9.9312, 76.2673),
}

# Rain and wet weather codes in WMO 4677 standard
RAIN_WMO_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}

_WMO = {
    "clear": {0, 1},
    "cloud": {2, 3},
    "fog": {45, 48},
    "drizzle": {51, 53, 55, 56, 57},
    "rain": {61, 63, 65, 66, 67, 80, 81, 82},
    "snow": {71, 73, 75, 77, 85, 86},
    "storm": {95, 96, 99},
}

_CONDITION_WORDS = {
    "clear": "clear",
    "cloud": "cloudy",
    "fog": "foggy",
    "drizzle": "drizzling",
    "rain": "raining",
    "snow": "snowing",
    "storm": "thundery",
    "unknown": "unsettled",
}


def condition_group(weather_code) -> str:
    try:
        number = int(weather_code)
    except (TypeError, ValueError):
        return "unknown"
    for group, codes in _WMO.items():
        if number in codes:
            return group
    return "unknown"


def map_weather_type(temperature_c: float, precipitation: float = 0.0, weather_code: int = 0) -> str:
    """
    Map conditions to: hot (>=28 C), cold (<=15 C), rainy (precipitation > 0 or rain codes), else mild.
    """
    if precipitation > 0 or int(weather_code) in RAIN_WMO_CODES:
        return "rainy"
    if temperature_c >= 28:
        return "hot"
    if temperature_c <= 15:
        return "cold"
    return "mild"


def get_teas_for_weather(weather_type: str, limit: int = 3):
    """Retrieve up to limit teas matching the weather type."""
    from core.models import Tea

    # Look for teas marked for this weather, or matching categories/moods
    try:
        qs = Tea.objects.filter(is_available=True) if hasattr(Tea, "is_available") else Tea.objects.filter(in_stock=True)
        if hasattr(Tea, "best_for_weather"):
            matching = list(qs.filter(best_for_weather=weather_type)[:limit])
            if len(matching) >= limit:
                return [tea.to_dict() for tea in matching]
        else:
            matching = []

        # Category/mood fallbacks
        type_categories = {
            "hot": ["tisane", "green", "white"],
            "cold": ["black", "dark", "blend"],
            "rainy": ["blend", "oolong", "black"],
            "mild": ["green", "oolong", "white"],
        }.get(weather_type, ["green", "oolong", "white"])

        extra = list(qs.filter(category__in=type_categories)[:limit])
        if not extra:
            extra = list(qs[:limit])
        return [tea.to_dict() for tea in extra[:limit]]
    except Exception as exc:
        log.warning("get_teas_for_weather failed: %s", exc)
        return []


def _fetch_open_meteo(url: str, timeout: float) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "maison-tisane/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f"HTTP {response.status} from Open-Meteo")
        return json.loads(response.read(20000).decode("utf-8"))


def get_weather_tea(lat: float, lon: float) -> dict:
    """
    Calls Open-Meteo with latitude and longitude.
    Returns {weather: {...}, teas: [...]}.
    Caches results per rounded lat/lon for 15 minutes.
    If the API fails, returns 3 'mild' teas with weather: null.
    """
    rounded_lat = round(float(lat), 2)
    rounded_lon = round(float(lon), 2)
    cache_key = f"weather_tea:{rounded_lat}:{rounded_lon}"

    cached = cache.get(cache_key)
    if cached:
        return cached

    url = (
        f"{ENDPOINT}?latitude={rounded_lat:.2f}&longitude={rounded_lon:.2f}"
        f"&current=temperature_2m,precipitation,weather_code"
    )
    timeout = float(getattr(settings, "EXTERNAL_API_TIMEOUT", 3))

    try:
        data = _fetch_open_meteo(url, timeout)

        current = data.get("current") or {}
        temp = float(current.get("temperature_2m", 20.0))
        precip = float(current.get("precipitation", 0.0))
        wcode = int(current.get("weather_code", 0))

        w_type = map_weather_type(temp, precip, wcode)
        group = condition_group(wcode)

        result = {
            "source": "api",
            "weather_type": w_type,
            "weather": {
                "temperature_c": round(temp, 1),
                "precipitation": precip,
                "weather_code": wcode,
                "weather_type": w_type,
                "condition": _CONDITION_WORDS.get(group, "unsettled"),
            },
            "teas": get_teas_for_weather(w_type, 3),
        }
        cache.set(cache_key, result, WEATHER_TEA_CACHE_SECONDS)
        return result

    except Exception as exc:
        log.warning("Open-Meteo call failed for lat=%s, lon=%s: %s", lat, lon, exc)
        fallback_result = {
            "source": "fallback",
            "weather_type": "mild",
            "weather": None,
            "teas": get_teas_for_weather("mild", 3),
        }
        return fallback_result


def _suggest_from_conditions(temperature_c: float, group: str) -> dict:
    wet = group in {"drizzle", "rain", "storm", "fog"}
    if temperature_c >= 28:
        return {
            "mood": "iced",
            "categories": ["tisane", "green", "white"],
            "reason": (
                f"It is {temperature_c:.0f} degrees, so this is a day for something "
                "cooling. Brew these at strength and pour them straight over ice."
            ),
        }
    if temperature_c >= 24:
        if wet:
            return {
                "mood": "comfort",
                "categories": ["oolong", "black", "blend"],
                "reason": (
                    f"Warm at {temperature_c:.0f} degrees but wet, which suits a "
                    "roasted oolong or a pot of chai more than anything delicate."
                ),
            }
        return {
            "mood": "afternoon",
            "categories": ["green", "oolong", "white"],
            "reason": (
                f"A mild {temperature_c:.0f} degrees. Good conditions for tasting "
                "something subtle, served hot but not scalding."
            ),
        }
    if temperature_c >= 16:
        return {
            "mood": "comfort",
            "categories": ["oolong", "black", "dark"],
            "reason": (
                f"Cool at {temperature_c:.0f} degrees. A roasted oolong or a malty "
                "black will hold its heat and its sweetness."
            ),
        }
    return {
        "mood": "comfort",
        "categories": ["dark", "blend", "black"],
        "reason": (
            f"Cold at {temperature_c:.0f} degrees. This is chai and puer weather: "
            "boiling water, heavy leaf, nothing subtle."
        ),
    }


def _seasonal(city: str, reason_prefix: str = "") -> dict:
    month = date.today().month
    if month in (3, 4, 5):
        season = "the hot weeks before the monsoon"
        payload = {"mood": "iced", "categories": ["tisane", "green", "white"]}
    elif month in (6, 7, 8, 9):
        season = "the monsoon"
        payload = {"mood": "digestive", "categories": ["green", "oolong", "tisane"]}
    elif month in (10, 11):
        season = "the turn into cooler weather"
        payload = {"mood": "afternoon", "categories": ["oolong", "black", "white"]}
    else:
        season = "the cool months"
        payload = {"mood": "comfort", "categories": ["black", "dark", "blend"]}

    payload.update({
        "source": "fallback",
        "city": city,
        "temperature_c": None,
        "condition": None,
        "season": season,
        "label": "Based on the season",
        "reason": (
            reason_prefix
            + f"We could not reach the weather service, so this is chosen for "
            f"{season} rather than for today in {city}."
        ).strip(),
        "site_code": SITE_WEATHER_SLOW,
    })
    return payload


def for_city(city: str | None = None, *, use_cache: bool = True) -> dict:
    name = (city or DEFAULT_CITY).strip().title()
    if name not in CITIES:
        name = DEFAULT_CITY

    cache_key = f"weather:v1:{name}"
    if use_cache:
        cached = cache.get(cache_key)
        if cached:
            return cached

    latitude, longitude = CITIES[name]
    timeout = float(getattr(settings, "EXTERNAL_API_TIMEOUT", 3))

    query = urllib.parse.urlencode({
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "current": "temperature_2m,weather_code",
    })
    url = f"{ENDPOINT}?{query}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "maison-tisane/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError(f"HTTP {response.status} from Open-Meteo")
            raw = response.read(20000).decode("utf-8")
        payload = json.loads(raw)
        current = payload.get("current") or {}
        if "temperature_2m" not in current:
            raise ValueError("response had no current.temperature_2m")

        temp = float(current["temperature_2m"])
        wcode = current.get("weather_code")
        group = condition_group(wcode)
        suggestion = _suggest_from_conditions(temp, group)

        result = {
            "source": "api",
            "city": name,
            "temperature_c": round(temp, 1),
            "condition": _CONDITION_WORDS.get(group, "unsettled"),
            "season": None,
            "label": f"Based on today's weather in {name}",
            "site_code": None,
            **suggestion,
        }
        if use_cache:
            cache.set(cache_key, result, CITY_CACHE_SECONDS)
        return result

    except Exception as exc:
        log.warning(
            "%s weather lookup failed for %s, using seasonal fallback: %s",
            SITE_WEATHER_SLOW,
            name,
            exc,
        )
        result = _seasonal(name)
        if use_cache:
            cache.set(cache_key, result, 120)
        return result


def last_status() -> dict:
    for name in (DEFAULT_CITY, *CITIES):
        cached = cache.get(f"weather:v1:{name}")
        if cached:
            return {
                "checked": True,
                "source": cached.get("source"),
                "city": cached.get("city"),
            }
    return {"checked": False, "source": None, "city": None}
