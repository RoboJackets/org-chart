from celery import shared_task
from django.conf import settings
from requests import get

from org.apiary import get_teams
from org.google import get_google_workspace_client
from org.keycloak import get_keycloak_access_token
from org.models import Person
from org.ramp import get_ramp_user, get_ramp_access_token


@shared_task
def update_google_workspace_user(  # pylint: disable=too-many-branches,too-many-statements
    local_user_id: int,
) -> None:
    """
    Update the Google Workspace profile for a given local user.
    """
    local_user = Person.objects.get(pk=local_user_id)
    keycloak_user = None
    ramp_user = None
    google_workspace_user_update = {}

    if local_user.keycloak_user_id is None:
        keycloak_user_search = get(
            url=settings.KEYCLOAK_SERVER + "/admin/realms/robojackets/users",
            headers={
                "Authorization": "Bearer " + get_keycloak_access_token(),
                "Accept": "application/json",
            },
            params={
                "username": local_user.username,
                "exact": "true",
            },
            timeout=(5, 5),
        )

        if keycloak_user_search.status_code != 200:
            raise Exception(
                "Failed to search Keycloak for OrgChart user: " + keycloak_user_search.text
            )

        if len(keycloak_user_search.json()) > 1:
            raise Exception(
                "Keycloak search returned multiple results for OrgChart user " + str(local_user.id)
            )

        if len(keycloak_user_search.json()) == 1:
            keycloak_user = keycloak_user_search.json()[0]

            local_user.keycloak_user_id = keycloak_user["id"]
            local_user.save()
    else:
        keycloak_user_response = get(
            url=settings.KEYCLOAK_SERVER
            + "/admin/realms/robojackets/users/"
            + str(local_user.keycloak_user_id),
            headers={
                "Authorization": "Bearer " + get_keycloak_access_token(),
                "Accept": "application/json",
            },
            timeout=(5, 5),
        )

        if keycloak_user_response.status_code != 200:
            raise Exception(
                "Failed to get Keycloak user for OrgChart user: " + keycloak_user_response.text
            )

        keycloak_user = keycloak_user_response.json()

    if local_user.ramp_user_id is None and keycloak_user is not None:
        if (
            "attributes" in keycloak_user
            and "rampUserId" in keycloak_user["attributes"]
            and len(keycloak_user["attributes"]["rampUserId"]) == 1
        ):
            local_user.ramp_user_id = keycloak_user["attributes"]["rampUserId"][0]
            local_user.save()

    if local_user.ramp_user_id is not None:
        ramp_user = get_ramp_user(str(local_user.ramp_user_id), get_ramp_access_token("users:read"))

    workspace = get_google_workspace_client()

    if local_user.google_workspace_user_id is None and keycloak_user is not None:
        if (
            "attributes" in keycloak_user
            and "googleWorkspaceAccount" in keycloak_user["attributes"]
            and len(keycloak_user["attributes"]["googleWorkspaceAccount"]) == 1
        ):
            workspace_user = workspace.get(
                userKey=keycloak_user["attributes"]["googleWorkspaceAccount"][0]
            ).execute()

            local_user.google_workspace_user_id = workspace_user["id"]
            local_user.save()

    if ramp_user is not None and "phone" in ramp_user and ramp_user["phone"] is not None:
        google_workspace_user_update["phones"] = [
            {
                "value": ramp_user["phone"],
                "type": "mobile",
            }
        ]

    if hasattr(local_user, "position"):
        position = local_user.position

        google_workspace_user_update["organizations"] = [
            {
                "title": position.name,
                "department": get_teams()[position.member_of_apiary_team],
                "primary": True,  # type: ignore
            },
        ]

        if (
            position.reports_to_position is not None
            and position.reports_to_position.person is not None
            and position.reports_to_position.person.google_workspace_user_id is not None
        ):
            manager = workspace.get(
                userKey=position.reports_to_position.person.google_workspace_user_id
            ).execute()

            google_workspace_user_update["relations"] = [
                {
                    "value": manager["primaryEmail"],
                    "type": "manager",
                },
            ]
        else:
            google_workspace_user_update["relations"] = []
    else:
        if local_user.member_of_apiary_team is not None:
            google_workspace_user_update["organizations"] = [
                {
                    "department": get_teams()[local_user.member_of_apiary_team],
                    "primary": True,  # type: ignore
                },
            ]
        else:
            google_workspace_user_update["organizations"] = []

        if (
            local_user.reports_to_position is not None
            and local_user.reports_to_position.person is not None
            and local_user.reports_to_position.person.google_workspace_user_id is not None
        ):
            manager = workspace.get(
                userKey=local_user.reports_to_position.person.google_workspace_user_id
            ).execute()

            google_workspace_user_update["relations"] = [
                {
                    "value": manager["primaryEmail"],
                    "type": "manager",
                },
            ]
        else:
            google_workspace_user_update["relations"] = []

    workspace.update(
        userKey=local_user.google_workspace_user_id, body=google_workspace_user_update
    ).execute()
