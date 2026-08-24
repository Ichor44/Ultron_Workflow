NAME = "skill_what_is_the_weather_like"
DESCRIPTION = "Get current weather and forecasts for any city using wttr.in (free, no API key required)."
TRIGGERS = ["weather", "what is the weather", "how's the weather", "temperature", "forecast", "is it raining", "weather today", "weather like"]

import urllib.request
import urllib.parse
import json


def run(city="", **kwargs):
    """Get current weather for a city.

    Args:
        city: City name (e.g., "London", "New York"). Empty returns local weather.

    Returns:
        Current weather summary string.
    """
    if not city:
        city = "auto"

    encoded_city = urllib.parse.quote(city)
    url = f"https://wttr.in/{encoded_city}?format=j1"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return f"Weather lookup failed: {e}"

    try:
        current = data["current_condition"][0]
        area = data["nearest_area"][0]

        area_name = area["areaName"][0]["value"]
        region = area["region"][0]["value"]
        country = area["country"][0]["value"]

        desc = current["weatherDesc"][0]["value"]
        temp_c = current["temp_C"]
        temp_f = current["temp_F"]
        feels_like_c = current["FeelsLikeC"]
        humidity = current["humidity"]
        wind_speed = current["windspeedKmph"]
        wind_dir = current["winddir16Point"]

        lines = [
            f"Weather for {area_name}, {region}, {country}:",
            f"  Conditions : {desc}",
            f"  Temperature: {temp_c}C ({temp_f}F)",
            f"  Feels like : {feels_like_c}C",
            f"  Humidity   : {humidity}%",
            f"  Wind       : {wind_speed} km/h {wind_dir}",
        ]

        # Add today's forecast
        today = data["weather"][0]
        lines.append(f"  Today      : {today['mintempC']}C to {today['maxtempC']}C")

        return "\n".join(lines)
    except (KeyError, IndexError) as e:
        return f"Weather data parse error: {e}"


if __name__ == "__main__":
    import sys
    city = sys.argv[1] if len(sys.argv) > 1 else ""
    print(run(city=city))
