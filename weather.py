import asyncio
import requests


async def get_weather(
    latitude: float = 59.3293,
    longitude: float = 18.0686,
    timezone: str = "auto"
):
    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": [
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "weather_code",
            "wind_speed_10m",
            "uv_index",
            "surface_pressure",
        ],
        "hourly": [
            "temperature_2m",
            "weather_code",
            "precipitation_probability",
            "visibility",
        ],
        "daily": [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "sunrise",
            "sunset",
        ],
        "timezone": timezone,
        "forecast_days": 7,
    }

    response = await asyncio.to_thread(
        requests.get,
        url,
        params=params,
        timeout=10
    )

    response.raise_for_status()
    return response.json()