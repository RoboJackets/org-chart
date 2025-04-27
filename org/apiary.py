from typing import Dict

from django.conf import settings
from django.core.cache import cache
from requests import get


def get_teams() -> Dict[int, str]:
    """
    Retrieve the map of team choices from Apiary.
    """
    cached_teams = cache.get("apiary_teams")
    if cached_teams is not None:
        return cached_teams  # type: ignore

    teams_response = get(
        url=settings.APIARY_SERVER + "/api/v1/teams",
        headers={
            "Authorization": "Bearer " + settings.APIARY_TOKEN,
            "Accept": "application/json",
        },
        timeout=(5, 5),
    )

    if teams_response.status_code != 200:
        raise Exception("Error retrieving teams from Apiary: " + teams_response.text)

    teams = {}
    for team in teams_response.json()["teams"]:
        teams[team["id"]] = team["name"]

    cache.set("apiary_teams", teams, timeout=None)

    return teams
