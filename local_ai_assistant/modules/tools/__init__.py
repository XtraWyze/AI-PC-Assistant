"""Specialized helper tools exposed to the LLM."""

from .get_location import get_location
from .get_time_date import get_time_date
from .get_weather import (
	get_air_quality,
	get_environment_overview,
	get_forecast,
	get_sunrise_sunset,
	get_weather,
)
from .open_file_location import run_tool as open_file_location
from .open_path import run_tool as open_path
from .open_website import open_website
from .web_access import fetch_page, search_web, summarize_page

TOOL_REGISTRY = {
	"get_time_date": get_time_date,
	"get_location": get_location,
	"get_weather": get_weather,
	"get_sunrise_sunset": get_sunrise_sunset,
	"get_forecast": get_forecast,
	"get_air_quality": get_air_quality,
	"get_environment_overview": get_environment_overview,
	"open_path": open_path,
	"open_file_location": open_file_location,
	"open_website": open_website,
	"search_web": search_web,
	"fetch_page": fetch_page,
	"summarize_page": summarize_page,
}

__all__ = [
	"TOOL_REGISTRY",
	"get_time_date",
	"get_location",
	"get_weather",
	"get_sunrise_sunset",
	"get_forecast",
	"get_air_quality",
	"get_environment_overview",
	"open_path",
	"open_file_location",
	"open_website",
	"search_web",
	"fetch_page",
	"summarize_page",
]
