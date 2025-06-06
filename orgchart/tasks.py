from celery import shared_task, Task
from django.conf import settings
from googleapiclient.errors import HttpError  # type: ignore
from requests import get

from org.apiary import get_apiary_user
from org.google import get_google_workspace_client
from org.keycloak import get_keycloak_access_token
from org.models import Person, Position
from org.ramp import get_ramp_user, get_ramp_access_token
from org.tasks import update_google_workspace_user


@shared_task
def import_ramp_user(  # pylint: disable=too-many-branches,too-many-statements
    ramp_user_id: str,
) -> None:
    """
    Import a Ramp user by ID
    """
    # determine if this is a valid ramp user id at all
    ramp_user = get_ramp_user(ramp_user_id, get_ramp_access_token("users:read"))

    # determine if we already have this ramp user id in our database
    try:
        Person.objects.get(ramp_user_id__iexact=ramp_user_id)

        return
    except Person.DoesNotExist:
        pass

    # determine if this ramp user is in keycloak
    keycloak_user_search = get(
        url=settings.KEYCLOAK_SERVER + "/admin/realms/robojackets/users",
        headers={
            "Authorization": "Bearer " + get_keycloak_access_token(),
            "Accept": "application/json",
        },
        params={
            "q": "rampUserId:" + ramp_user_id,
        },
        timeout=(5, 5),
    )

    if keycloak_user_search.status_code != 200:
        raise Exception("Failed to search Keycloak for Ramp user: " + keycloak_user_search.text)

    if len(keycloak_user_search.json()) == 0:
        # try searching by googleWorkspaceAccount instead
        keycloak_user_search = get(
            url=settings.KEYCLOAK_SERVER + "/admin/realms/robojackets/users",
            headers={
                "Authorization": "Bearer " + get_keycloak_access_token(),
                "Accept": "application/json",
            },
            params={
                "q": "googleWorkspaceAccount:" + ramp_user["email"],
            },
            timeout=(5, 5),
        )

        if keycloak_user_search.status_code != 200:
            raise Exception("Failed to search Keycloak for Ramp user: " + keycloak_user_search.text)

        if len(keycloak_user_search.json()) == 0:
            raise Exception("Keycloak search returned no results for Ramp user " + ramp_user_id)

        if len(keycloak_user_search.json()) > 1:
            raise Exception(
                "Keycloak search returned multiple results for Ramp user " + ramp_user_id
            )

    if len(keycloak_user_search.json()) > 1:
        raise Exception("Keycloak search returned multiple results for Ramp user " + ramp_user_id)

    keycloak_user = keycloak_user_search.json()[0]

    # create user if needed
    try:
        this_person = Person.objects.get(
            username__iexact=keycloak_user["username"], ramp_user_id__isnull=True
        )

        this_person.ramp_user_id = ramp_user_id
        this_person.save()
    except Person.DoesNotExist:
        this_person = Person.objects.create_user(
            username=keycloak_user["username"],
            email=keycloak_user["email"],
            password=None,
            first_name=ramp_user["first_name"],
            last_name=ramp_user["last_name"],
            keycloak_user_id=keycloak_user["id"],
            ramp_user_id=ramp_user_id,
            is_active=True,
            is_staff=settings.DEBUG,
            is_superuser=settings.DEBUG,
        )

    apiary_user = get_apiary_user(keycloak_user["username"])
    if apiary_user is None:
        raise Exception("Failed to fetch user from Apiary")

    # if ramp manager is not blank and ramp manager is not in database then import manager
    ramp_manager = None

    if ramp_user["manager_id"] is not None:
        try:
            ramp_manager = Person.objects.get(ramp_user_id__iexact=ramp_user["manager_id"])

        except Person.DoesNotExist:
            import_ramp_user(ramp_user["manager_id"])

            ramp_manager = Person.objects.get(ramp_user_id__iexact=ramp_user["manager_id"])

    if not this_person.manual_hierarchy:
        if (
            "primary_team" in apiary_user
            and apiary_user["primary_team"] is not None
            and "id" in apiary_user["primary_team"]
            and apiary_user["primary_team"]["id"] is not None
        ):
            apiary_primary_team_id = apiary_user["primary_team"]["id"]

            if this_person.member_of_apiary_team != apiary_primary_team_id:
                this_person.member_of_apiary_team = apiary_primary_team_id

        if (
            "manager" in apiary_user
            and apiary_user["manager"] is not None
            and "id" in apiary_user["manager"]
            and apiary_user["manager"]["id"] is not None
        ):
            try:
                apiary_manager = Person.objects.get(
                    apiary_user_id__exact=apiary_user["manager"]["id"]
                )

                apiary_manager_position = Position.objects.get(person=apiary_manager)

                if ramp_manager is not None:
                    ramp_manager_position = Position.objects.get(person=ramp_manager)

                    if ramp_manager_position.id == apiary_manager_position.id:
                        this_person.reports_to_position = apiary_manager_position
                    else:
                        this_person.reports_to_position = ramp_manager_position
                        this_person.manual_hierarchy = True

                elif this_person.reports_to_position != apiary_manager_position:
                    this_person.reports_to_position = apiary_manager_position

            except Position.DoesNotExist:
                pass
            except Person.DoesNotExist:
                pass

        this_person.save()


@shared_task(bind=True, retry_backoff=True, max_retries=5, retry_jitter=True, retry_backoff_max=60)
def import_google_workspace_user(self: Task, google_workspace_user_id: str) -> None:  # type: ignore
    """
    Import a Google Workspace user by ID
    """
    try:
        workspace_user = (
            get_google_workspace_client().get(userKey=google_workspace_user_id).execute()
        )
    except HttpError as e:
        if e.status_code == 404:
            raise self.retry(exc=e) from e

        raise e

    keycloak_token = get_keycloak_access_token()

    try:
        Person.objects.get(google_workspace_user_id__iexact=workspace_user["id"])
    except Person.DoesNotExist as exc:
        # determine if this workspace user is in keycloak
        keycloak_user_search = get(
            url=settings.KEYCLOAK_SERVER + "/admin/realms/robojackets/users",
            headers={
                "Authorization": "Bearer " + keycloak_token,
                "Accept": "application/json",
            },
            params={
                "q": "googleWorkspaceAccount:" + workspace_user["primaryEmail"],
            },
            timeout=(5, 5),
        )

        if keycloak_user_search.status_code != 200:
            raise Exception(
                "Failed to search Keycloak for Google Workspace user: " + keycloak_user_search.text
            ) from exc

        if len(keycloak_user_search.json()) > 1:
            raise Exception(
                "Keycloak search returned multiple results for Google Workspace user "
                + workspace_user["primaryEmail"]
            ) from exc

        keycloak_user = keycloak_user_search.json()[0]

        try:
            local_user = Person.objects.get(
                username__iexact=keycloak_user["username"], google_workspace_user_id__isnull=True
            )

            local_user.google_workspace_user_id = workspace_user["id"]
            local_user.save()

            update_google_workspace_user.delay_on_commit(local_user.id)
        except Person.DoesNotExist:
            this_ramp_user_id = None

            if (
                "attributes" in keycloak_user
                and "rampUserId" in keycloak_user["attributes"]
                and len(keycloak_user["attributes"]["rampUserId"]) == 1
            ):
                this_ramp_user_id = keycloak_user["attributes"]["rampUserId"][0]

            local_user = Person.objects.create_user(
                username=keycloak_user["username"],
                email=keycloak_user["email"],
                password=None,
                first_name=workspace_user["name"]["givenName"],
                last_name=workspace_user["name"]["familyName"],
                keycloak_user_id=keycloak_user["id"],
                ramp_user_id=this_ramp_user_id,
                is_active=keycloak_user["enabled"],
                is_staff=settings.DEBUG,
                is_superuser=settings.DEBUG,
            )

            update_google_workspace_user.delay_on_commit(local_user.id)
