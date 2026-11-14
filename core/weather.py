"""
Weather module wrapper.
Delegates to core.services.weather.
"""

from core.services import weather as _weather_svc
from core.services.weather import (
    CITIES,
    DEFAULT_CITY,
    condition_group,
    for_city,
    get_weather_tea,
    last_status,
    map_weather_type,
)
