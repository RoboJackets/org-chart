import logging
from typing import List, Dict

from django.conf import settings
from requests import post, get, patch


def get_ramp_access_token(scope: str) -> str:
    """
    Get an access token for the Ramp API.
    """
    ramp_access_token_response = post(
        url="https://api.ramp.com/developer/v1/token",
        data={
            "grant_type": "client_credentials",
            "scope": scope,
        },
        auth=(
            settings.RAMP_CLIENT_ID,
            settings.RAMP_CLIENT_SECRET,
        ),
        timeout=(5, 5),
    )

    if ramp_access_token_response.status_code != 200:
        raise Exception("Failed to get access token from Ramp: " + ramp_access_token_response.text)

    return ramp_access_token_response.json()["access_token"]  # type: ignore


def get_ramp_users(token: str) -> List[Dict[str, str]]:
    """
    Get all Ramp users.
    """
    ramp_users_response = get(
        url="https://api.ramp.com/developer/v1/users",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
        },
        timeout=(5, 5),
        params={
            "page_size": 100,
        }
    )

    if ramp_users_response.status_code != 200 or "data" not in ramp_users_response.json():
        raise Exception("Failed to get users from Ramp: " + ramp_users_response.text)

    return ramp_users_response.json()["data"]  # type: ignore


def get_ramp_user(user_id: str, token: str) -> Dict[str, str]:
    """
    Get a single Ramp user.
    """
    ramp_user_response = get(
        url="https://api.ramp.com/developer/v1/users/" + user_id,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
        },
        timeout=(5, 5),
    )

    if ramp_user_response.status_code != 200 or "id" not in ramp_user_response.json():
        raise Exception("Failed to get user from Ramp: " + ramp_user_response.text)

    return ramp_user_response.json()  # type: ignore


def update_ramp_manager(user_id: str, manager_id: str, token: str) -> None:
    """
    Update a user's manager in Ramp.
    """
    logging.debug("Updating Ramp manager for user %s to %s", user_id, manager_id)
    ramp_response = patch(
        url="https://api.ramp.com/developer/v1/users/" + user_id,
        json={
            "direct_manager_id": manager_id,
            "auto_promote": True,
        },
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
        },
        timeout=(5, 5),
    )

    if ramp_response.status_code != 200:
        raise Exception("Failed to update manager in Ramp: " + ramp_response.text)
