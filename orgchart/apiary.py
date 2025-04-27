from typing import Tuple

from django.conf import settings
from django.core.cache import cache
from requests import get

from org.models import Person, Position


def find_or_create_local_user_for_apiary_user_id(apiary_user_id: int) -> Tuple[Person, int]:
    """
    Given an Apiary user ID, find or create the local user with that ID.
    Also attempt to recursively create their management chain.
    """
    try:
        this_user = Person.objects.get(apiary_user_id__exact=apiary_user_id)

        return this_user, 0
    except Person.DoesNotExist as exc:
        users_created = 0

        apiary_user = cache.get("apiary_user_" + str(apiary_user_id))

        if apiary_user is None:

            user_response = get(
                url=settings.APIARY_SERVER + "/api/v1/users/" + str(apiary_user_id),
                headers={
                    "Authorization": "Bearer " + settings.APIARY_TOKEN,
                    "Accept": "application/json",
                },
                timeout=(5, 5),
            )

            if user_response.status_code != 200:
                raise Exception("Unable to fetch user from Apiary: " + user_response.text) from exc
            if "user" not in user_response.json():
                raise Exception("Unable to fetch user from Apiary: " + user_response.text) from exc

            apiary_user = user_response.json()["user"]
            cache.set("apiary_user_" + str(apiary_user_id), apiary_user, timeout=None)

        this_user_reports_to_position = None
        this_user_primary_team = None

        if (
            "primary_team" in apiary_user
            and apiary_user["primary_team"] is not None
            and "id" in apiary_user["primary_team"]
            and apiary_user["primary_team"]["id"] is not None
        ):
            this_user_primary_team = apiary_user["primary_team"]["id"]

        this_user = Person.objects.create_user(
            username=apiary_user["uid"],
            email=apiary_user["gt_email"],
            password=None,
            first_name=apiary_user["first_name"],
            last_name=apiary_user["last_name"],
            apiary_user_id=apiary_user["id"],
            reports_to_position=this_user_reports_to_position,
            member_of_apiary_team=this_user_primary_team,
            keycloak_user_id=None,
            ramp_user_id=None,
            is_active=apiary_user["is_access_active"],
            is_staff=settings.DEBUG,
            is_superuser=settings.DEBUG,
        )

        if (
            "manager" in apiary_user
            and apiary_user["manager"] is not None
            and "id" in apiary_user["manager"]
            and apiary_user["manager"]["id"] is not None
        ):
            (this_users_manager, users_created) = find_or_create_local_user_for_apiary_user_id(
                apiary_user["manager"]["id"]
            )

            try:
                this_user_reports_to_position = Position.objects.get(person=this_users_manager)

                this_user.reports_to_position = this_user_reports_to_position
                this_user.save()
            except Position.DoesNotExist:
                pass

        users_created += 1

        return this_user, users_created
