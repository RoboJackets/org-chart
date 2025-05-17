from django.conf import settings
from requests import post


def get_keycloak_access_token() -> str:
    """
    Get an access token for Keycloak.
    """
    keycloak_access_token_response = post(
        url=settings.KEYCLOAK_SERVER + "/realms/master/protocol/openid-connect/token",
        data={
            "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
            "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
        timeout=(
            5,
            5,
        ),
    )

    if keycloak_access_token_response.status_code != 200:
        raise Exception(
            "Failed to get access token from Keycloak: " + keycloak_access_token_response.text
        )

    return keycloak_access_token_response.json()["access_token"]  # type: ignore
