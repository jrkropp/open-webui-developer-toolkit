"""
title: Basic Tools
id: basic_tools
description: Toolkit showcasing echo, calculator and weather functions.
author: open-webui
license: MIT
version: 0.0.0
requirements: requests
"""

from __future__ import annotations

import os
from datetime import datetime

import requests
from pydantic import BaseModel, Field


class Tool:
    class Valves(BaseModel):
        pass

    class EchoInput(BaseModel):
        text: str = Field(..., description="Text to echo back")

    class CalcInput(BaseModel):
        equation: str = Field(..., description="Math equation to evaluate")

    class WeatherInput(BaseModel):
        city: str = Field("New York, NY", description="City for the weather report")

    specs = [
        {
            "name": "echo",
            "description": "Return the provided text.",
            "parameters": EchoInput.model_json_schema(),
        },
        {
            "name": "calculator",
            "description": "Evaluate a math equation.",
            "parameters": CalcInput.model_json_schema(),
        },
        {
            "name": "get_current_time",
            "description": "Return the current time.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "get_current_weather",
            "description": "Get the current weather for a city.",
            "parameters": WeatherInput.model_json_schema(),
        },
    ]

    def __init__(self) -> None:
        self.valves = self.Valves()

    async def echo(self, text: str) -> str:
        """Return ``text`` as-is.

        :param text: The string to echo back.
        """
        return text

    async def calculator(self, equation: str) -> str:
        """Evaluate a math expression.

        :param equation: Expression to evaluate.
        """
        try:
            result = eval(equation)
            return f"{equation} = {result}"
        except Exception:
            return "Invalid equation"

    async def get_current_time(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async def get_current_weather(self, city: str = "New York, NY") -> str:
        """Look up the weather for ``city`` using OpenWeatherMap."""

        api_key = os.getenv("OPENWEATHER_API_KEY")
        if not api_key:
            return "OPENWEATHER_API_KEY is not set"
        try:
            resp = requests.get(
                "http://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": api_key, "units": "metric"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["weather"][0]["description"]
        except requests.RequestException:
            return "Error fetching weather data"

