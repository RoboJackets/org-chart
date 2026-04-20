from typing import Dict, Any

from django.conf import settings
from django.core.cache import cache
from requests import get, post


def get_apiary_access_token() -> str:
    """
    Get an access token for Apiary via OAuth 2.0 client credentials.
    """
    apiary_access_token_response = post(
        url=settings.APIARY_SERVER + "/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.APIARY_CLIENT_ID,
            "client_secret": settings.APIARY_CLIENT_SECRET,
        },
        timeout=(5, 5),
    )

    if apiary_access_token_response.status_code != 200:
        raise Exception(
            "Failed to get access token from Apiary: " + apiary_access_token_response.text
        )

    return apiary_access_token_response.json()["access_token"]  # type: ignore


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
            "Authorization": "Bearer " + get_apiary_access_token(),
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
            "Authorization": "Bearer " + get_apiary_access_token(),
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
