from typing import Dict, Any

from django.conf import settings
from django.core.cache import cache
from requests import get


def get_teams() -> Dict[int, str]:
    """
    Get the map of team choices from Apiary.
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


def get_apiary_user(identifier: str) -> Any | None:
    """
    Get an Apiary user based on a unique identifier, typically Apiary ID or username.
    """
    apiary_user = cache.get("apiary_user_" + identifier)

    if apiary_user is not None:
        return apiary_user

    user_response = get(
        url=settings.APIARY_SERVER + "/api/v1/users/" + identifier,
        headers={
            "Authorization": "Bearer " + settings.APIARY_TOKEN,
            "Accept": "application/json",
        },
        timeout=(5, 5),
    )

    if user_response.status_code == 404:
        return None

    if user_response.status_code != 200:
        raise Exception("Unable to fetch user from Apiary: " + user_response.text)

    if "user" not in user_response.json():
        raise Exception("Unable to fetch user from Apiary: " + user_response.text)

    apiary_user = user_response.json()["user"]

    cache.set("apiary_user_" + identifier, apiary_user, timeout=None)

    return apiary_user
