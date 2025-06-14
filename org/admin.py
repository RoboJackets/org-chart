import uuid
from collections import defaultdict
from gettext import ngettext
from typing import Literal, List, Dict, Any

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.admin.options import InlineModelAdmin
from django.contrib.auth.admin import UserAdmin
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.core.cache import cache
from hubspot import HubSpot  # type: ignore
from requests import get, patch

from orgchart.apiary import find_or_create_local_user_for_apiary_user_id
from .apiary import get_teams, get_apiary_user
from .google import get_google_workspace_users
from .keycloak import get_keycloak_access_token
from .models import Person, Position
from .ramp import get_ramp_users, get_ramp_access_token, get_ramp_user, update_ramp_manager
from .tasks import update_google_workspace_user


class InlinePositionAdmin(admin.StackedInline):  # type: ignore
    """
    Show a person's position on their edit page
    """

    model = Position
    extra = 0
    can_delete = False
    fields = (
        "name",
        "manages_apiary_team",
        "member_of_apiary_team",
        "reports_to_position",
        "person",
    )
    readonly_fields = fields

    def has_change_permission(self, request, obj=None) -> Literal[False]:  # type: ignore
        return False

    def has_add_permission(self, request, obj=None) -> Literal[False]:  # type: ignore
        return False

    def has_delete_permission(self, request, obj=None) -> Literal[False]:  # type: ignore
        return False

    def get_readonly_fields(self, request, obj=None) -> List[str]:  # type: ignore
        return list(super().get_fields(request, obj))  # type: ignore


class ReportsToPositionAdmin(admin.TabularInline):  # type: ignore
    """
    Show the positions reporting to a position on its edit page
    """

    verbose_name = "Reporting position"
    model = Position
    extra = 0
    fields = (
        "name",
        "manages_apiary_team",
        "member_of_apiary_team",
        "reports_to_position",
        "person",
    )
    readonly_fields = fields
    fk_name = "reports_to_position"
    can_delete = False

    def has_change_permission(self, request, obj=None) -> Literal[False]:  # type: ignore
        return False

    def has_add_permission(self, request, obj=None) -> Literal[False]:  # type: ignore
        return False

    def has_delete_permission(self, request, obj=None) -> Literal[False]:  # type: ignore
        return False

    def get_readonly_fields(self, request, obj=None) -> List[str]:  # type: ignore
        return list(super().get_fields(request, obj))  # type: ignore


class InlinePersonAdmin(admin.TabularInline):  # type: ignore
    """
    Show the people reporting to a position on its edit page
    """

    verbose_name = "Direct report"
    model = Person
    extra = 0
    fields = ("username", "first_name", "last_name", "member_of_apiary_team", "reports_to_position")
    readonly_fields = fields
    can_delete = False

    def has_change_permission(self, request, obj=None) -> Literal[False]:  # type: ignore
        return False

    def has_add_permission(self, request, obj=None) -> Literal[False]:  # type: ignore
        return False

    def has_delete_permission(self, request, obj=None) -> Literal[False]:  # type: ignore
        return False

    def get_readonly_fields(self, request, obj=None) -> List[str]:  # type: ignore
        return list(super().get_fields(request, obj))  # type: ignore

    def get_queryset(self, request: HttpRequest) -> QuerySet[Person]:
        return super().get_queryset(request).filter(position__isnull=True)


class PersonAdmin(UserAdmin):  # type: ignore
    """
    Model admin configuration for Person
    """

    fieldsets = (
        (None, {"fields": ("username",)}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        (
            "Linked accounts",
            {
                "fields": (
                    "apiary_user_id",
                    "keycloak_user_id",
                    "ramp_user_id",
                    "google_workspace_user_id",
                    "hubspot_user_id",
                )
            },
        ),
        (
            "Organization hierarchy",
            {
                "fields": (
                    "reports_to_position",
                    "title",
                    "member_of_apiary_team",
                    "manual_hierarchy",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    list_display = [
        "username",
        "first_name",
        "last_name",
        "is_active",
        "member_of_apiary_team",
        "reports_to_position",
        "manual_hierarchy",
    ]
    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        "member_of_apiary_team",
        "reports_to_position",
        "manual_hierarchy",
    )
    inlines = (InlinePositionAdmin,)
    add_fieldsets = (
        (None, {"fields": ("username", "usable_password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        (
            "Organization hierarchy",
            {"fields": ("reports_to_position", "member_of_apiary_team", "manual_hierarchy")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )

    def get_inline_instances(self, request, obj=None) -> List[InlineModelAdmin]:  # type: ignore
        return (  # pylint: disable=simplify-boolean-expression
            obj and super().get_inline_instances(request, obj) or []
        )

    def changelist_view(
        self, request: HttpRequest, extra_context: Dict[str, Any] | None = None
    ) -> HttpResponse:
        if "action" in request.POST and request.POST["action"] in (
            "fetch_users_from_keycloak",
            "fetch_hierarchy_from_apiary",
            "reconcile_ramp_users",
            "reconcile_google_workspace_users",
            "reconcile_hubspot_users",
        ):
            r = request.POST.copy()
            for p in Person.objects.all():
                r.update({ACTION_CHECKBOX_NAME: str(p.id)})
            request.POST = r  # type: ignore
        return super().changelist_view(request, extra_context)

    def save_model(  # pylint: disable=too-many-branches
        self, request: HttpRequest, obj: Person, form: Any, change: Any
    ) -> None:
        super().save_model(request, obj, form, change)

        person = obj

        if person.ramp_user_id is not None:
            ramp_token = get_ramp_access_token("users:read users:write")

            ramp_user = get_ramp_user(str(person.ramp_user_id), ramp_token)

            if hasattr(person, "position"):
                if (
                    person.position.reports_to_position is None
                    and ramp_user["manager_id"] is not None
                ):
                    self.message_user(
                        request,
                        mark_safe(
                            '<a href="https://app.ramp.com/people/all/'  # noqa
                            + ramp_user["id"]
                            + '">'
                            + str(person)
                            + "</a> should not have a manager in Ramp, because "
                            + '<a href="'
                            + reverse("admin:org_position_change", args=(person.position.id,))
                            + '">'
                            + str(person.position)
                            + "</a> does not have a reporting position, however managers cannot be cleared via API. Update this person manually in Ramp if needed."  # noqa
                        ),
                        messages.WARNING,
                    )

                if person.position.reports_to_position is not None:
                    if person.position.reports_to_position.person is None:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="'
                                + reverse(
                                    "admin:org_position_change",
                                    args=(person.position.reports_to_position.id,),
                                )
                                + '">'
                                + str(person.position.reports_to_position)
                                + "</a> in Ramp, but this position is vacant."
                            ),
                            messages.WARNING,
                        )
                    elif person.position.reports_to_position.person.ramp_user_id is None:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="'
                                + reverse(
                                    "admin:org_person_change",
                                    args=(person.position.reports_to_position.person.id,),
                                )
                                + '">'
                                + str(person.position.reports_to_position.person)
                                + "</a> in Ramp, but "
                                + '<a href="'
                                + reverse(
                                    "admin:org_person_change",
                                    args=(person.position.reports_to_position.person.id,),
                                )
                                + '">'
                                + str(person.position.reports_to_position.person)
                                + "</a> does not have a Ramp account."
                            ),
                            messages.WARNING,
                        )
                    else:
                        update_ramp_manager(
                            ramp_user["id"],
                            str(person.position.reports_to_position.person.ramp_user_id),
                            ramp_token,
                        )

                        self.message_user(
                            request,
                            mark_safe(
                                'Updated manager for <a href="https://app.ramp.com/people/all/'  # noqa
                                + ramp_user["id"]
                                + '">'
                                + str(person)
                                + '</a> to <a href="https://app.ramp.com/people/all/'
                                + str(person.position.reports_to_position.person.ramp_user_id)
                                + '">'
                                + str(person.position.reports_to_position.person)
                                + "</a> in Ramp."
                            ),
                            messages.SUCCESS,
                        )
            else:
                if person.reports_to_position is None and ramp_user["manager_id"] is not None:
                    self.message_user(
                        request,
                        mark_safe(
                            '<a href="https://app.ramp.com/people/all/'
                            + ramp_user["id"]
                            + '">'
                            + str(person)
                            + "</a> should not have a manager in Ramp, because this person does not have a reporting position, however managers cannot be cleared via API. Update this person manually in Ramp if needed."  # noqa
                        ),
                        messages.WARNING,
                    )

                if person.reports_to_position is not None:
                    if person.reports_to_position.person is None:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="'
                                + reverse(
                                    "admin:org_position_change",
                                    args=(person.reports_to_position.id,),
                                )
                                + '">'
                                + str(person.reports_to_position)
                                + "</a> in Ramp, but this position is vacant."
                            ),
                            messages.WARNING,
                        )
                    elif person.reports_to_position.person.ramp_user_id is None:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="'
                                + reverse(
                                    "admin:org_person_change",
                                    args=(person.reports_to_position.person.id,),
                                )
                                + '">'
                                + str(person.reports_to_position.person)
                                + "</a> in Ramp, but "
                                + '<a href="'
                                + reverse(
                                    "admin:org_person_change",
                                    args=(person.reports_to_position.person.id,),
                                )
                                + '">'
                                + str(person.reports_to_position.person)
                                + "</a> does not have a Ramp account."
                            ),
                            messages.WARNING,
                        )
                    elif ramp_user[
                        "manager_id"
                    ] is None or person.reports_to_position.person.ramp_user_id != uuid.UUID(
                        ramp_user["manager_id"]
                    ):
                        update_ramp_manager(
                            ramp_user["id"],
                            str(person.reports_to_position.person.ramp_user_id),
                            ramp_token,
                        )

                        self.message_user(
                            request,
                            mark_safe(
                                'Updated manager for <a href="https://app.ramp.com/people/all/'  # noqa
                                + ramp_user["id"]
                                + '">'
                                + str(person)
                                + '</a> to <a href="https://app.ramp.com/people/all/'
                                + str(person.reports_to_position.person.ramp_user_id)
                                + '">'
                                + str(person.reports_to_position.person)
                                + "</a> in Ramp."
                            ),
                            messages.SUCCESS,
                        )

        update_google_workspace_user.delay_on_commit(obj.id)  # type: ignore

    actions = [
        "fetch_users_from_keycloak",
        "fetch_hierarchy_from_apiary",
        "reconcile_ramp_users",
        "reconcile_google_workspace_users",
        "reconcile_hubspot_users",
    ]

    @admin.action(permissions=["add"], description="Fetch people from Keycloak")
    def fetch_users_from_keycloak(  # pylint: disable=too-many-branches
        self, request: HttpRequest, queryset: QuerySet[Person]  # pylint: disable=unused-argument
    ) -> None:
        """
        Fetch user information from Keycloak and update or create local users as needed
        """
        keycloak_user_list_response = get(
            url=settings.KEYCLOAK_SERVER + "/admin/realms/robojackets/users",
            headers={
                "Authorization": "Bearer " + get_keycloak_access_token(),
            },
            params={
                "max": 1000,
            },
            timeout=(
                5,
                5,
            ),
        )

        if keycloak_user_list_response.status_code != 200:
            self.message_user(
                request,
                "Error retrieving people from Keycloak: " + keycloak_user_list_response.text,
                messages.ERROR,
            )
            return

        updated_active_flag_count = 0
        updated_keycloak_user_id_count = 0
        updated_ramp_user_id_count = 0
        added_new_person_count = 0

        for keycloak_user in keycloak_user_list_response.json():
            this_ramp_user_id = None

            if (
                "attributes" in keycloak_user
                and "rampUserId" in keycloak_user["attributes"]
                and len(keycloak_user["attributes"]["rampUserId"]) == 1
            ):
                this_ramp_user_id = keycloak_user["attributes"]["rampUserId"][0]

            try:
                this_person = Person.objects.get(keycloak_user_id__iexact=keycloak_user["id"])
            except Person.DoesNotExist:
                try:
                    this_person = Person.objects.get(username__iexact=keycloak_user["username"])
                    this_person.keycloak_user_id = keycloak_user["id"]
                    updated_keycloak_user_id_count += 1
                except Person.DoesNotExist:
                    this_person = Person.objects.create_user(
                        username=keycloak_user["username"],
                        email=keycloak_user["email"],
                        password=None,
                        first_name=keycloak_user["firstName"],
                        last_name=keycloak_user["lastName"],
                        keycloak_user_id=keycloak_user["id"],
                        ramp_user_id=this_ramp_user_id,
                        is_active=keycloak_user["enabled"],
                        is_staff=settings.DEBUG,
                        is_superuser=settings.DEBUG,
                    )
                    added_new_person_count += 1

            if this_person.is_active != keycloak_user["enabled"]:
                updated_active_flag_count += 1

            if this_person.ramp_user_id is None and this_ramp_user_id is not None:
                updated_ramp_user_id_count += 1

            this_person.email = keycloak_user["email"]
            this_person.first_name = keycloak_user["firstName"]
            this_person.last_name = keycloak_user["lastName"]
            this_person.ramp_user_id = this_ramp_user_id
            this_person.is_active = keycloak_user["enabled"]
            this_person.save()

        if updated_active_flag_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Updated active status for %d person.",
                    "Updated active status for %d people.",
                    updated_active_flag_count,
                )
                % updated_active_flag_count,
                messages.SUCCESS,
            )

        if updated_keycloak_user_id_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Updated Keycloak user ID for %d person.",
                    "Updated Keycloak user IDs for %d people.",
                    updated_keycloak_user_id_count,
                )
                % updated_keycloak_user_id_count,
                messages.SUCCESS,
            )

        if updated_ramp_user_id_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Updated Ramp user ID for %d person.",
                    "Updated Ramp user IDs for %d people.",
                    updated_ramp_user_id_count,
                )
                % updated_ramp_user_id_count,
                messages.SUCCESS,
            )

        if added_new_person_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Added %d person.",
                    "Added %d people.",
                    added_new_person_count,
                )
                % added_new_person_count,
                messages.SUCCESS,
            )

        if (
            updated_active_flag_count == 0
            and updated_ramp_user_id_count == 0
            and updated_keycloak_user_id_count == 0
            and added_new_person_count == 0
        ):
            self.message_user(
                request,
                "No changes made.",
                messages.SUCCESS,
            )

    @admin.action(permissions=["change"], description="Fetch hierarchy from Apiary")
    def fetch_hierarchy_from_apiary(  # pylint: disable=too-many-branches,too-many-statements
        self, request: HttpRequest, queryset: QuerySet[Person]  # pylint: disable=unused-argument
    ) -> None:
        """
        Fetch user information from Apiary and update primary team and reporting position as needed
        """
        updated_active_flag_count = 0
        updated_apiary_user_id_count = 0
        updated_primary_team_count = 0
        updated_reports_to_position_count = 0

        for person in Person.objects.all():
            apiary_user = get_apiary_user(person.username)

            if apiary_user is None:
                if person.is_active:
                    person.is_active = False
                    person.save()

                    self.message_user(
                        request,
                        mark_safe(
                            '<a href="'
                            + reverse("admin:org_person_change", args=(person.id,))
                            + '">'
                            + str(person)
                            + "</a> was not found in Apiary, and was therefore deactivated in OrgChart."  # noqa
                        ),
                        messages.WARNING,
                    )

                    updated_active_flag_count += 1
                    continue

                self.message_user(
                    request,
                    mark_safe(
                        '<a href="'
                        + reverse("admin:org_person_change", args=(person.id,))
                        + '">'
                        + str(person)
                        + "</a> was not found in Apiary."
                    ),
                    messages.WARNING,
                )
                continue

            if person.is_active != apiary_user["is_access_active"]:
                person.is_active = apiary_user["is_access_active"]
                updated_active_flag_count += 1

            if not person.manual_hierarchy:
                if (
                    "primary_team" in apiary_user
                    and apiary_user["primary_team"] is not None
                    and "id" in apiary_user["primary_team"]
                    and apiary_user["primary_team"]["id"] is not None
                ):
                    apiary_primary_team_id = apiary_user["primary_team"]["id"]

                    if person.member_of_apiary_team != apiary_primary_team_id:
                        person.member_of_apiary_team = apiary_primary_team_id
                        updated_primary_team_count += 1

                if (
                    "manager" in apiary_user
                    and apiary_user["manager"] is not None
                    and "id" in apiary_user["manager"]
                    and apiary_user["manager"]["id"] is not None
                ):
                    try:
                        person_reports_to_position = Position.objects.get(
                            person=Person.objects.get(
                                apiary_user_id__exact=apiary_user["manager"]["id"]
                            )
                        )

                        if person.reports_to_position != person_reports_to_position:
                            person.reports_to_position = person_reports_to_position
                            updated_reports_to_position_count += 1

                    except Position.DoesNotExist:
                        pass
                    except Person.DoesNotExist:
                        pass

            if person.apiary_user_id is None:
                person.apiary_user_id = apiary_user["id"]
                updated_apiary_user_id_count += 1
            elif person.apiary_user_id != apiary_user["id"]:
                self.message_user(
                    request,
                    mark_safe(
                        '<a href="'
                        + reverse("admin:org_person_change", args=(person.id,))
                        + '">'
                        + str(person)
                        + "</a> has an Apiary user ID within OrgChart, but it does not match their actual Apiary user ID."  # noqa
                    ),
                    messages.WARNING,
                )

            person.save()

        if updated_active_flag_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Updated active status for %d person.",
                    "Updated active status for %d people.",
                    updated_active_flag_count,
                )
                % updated_active_flag_count,
                messages.SUCCESS,
            )

        if updated_apiary_user_id_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Updated Apiary user ID for %d person.",
                    "Updated Apiary user ID for %d people.",
                    updated_apiary_user_id_count,
                )
                % updated_apiary_user_id_count,
                messages.SUCCESS,
            )

        if updated_primary_team_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Updated primary team for %d person.",
                    "Updated primary team for %d people.",
                    updated_primary_team_count,
                )
                % updated_primary_team_count,
                messages.SUCCESS,
            )

        if updated_reports_to_position_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Updated reporting position for %d person.",
                    "Updated reporting position for %d people.",
                    updated_reports_to_position_count,
                )
                % updated_reports_to_position_count,
                messages.SUCCESS,
            )

        if (
            updated_active_flag_count == 0
            and updated_apiary_user_id_count == 0
            and updated_primary_team_count == 0
            and updated_reports_to_position_count == 0
        ):
            self.message_user(
                request,
                "No changes made.",
                messages.SUCCESS,
            )

    @admin.action(permissions=["change"], description="Reconcile Ramp users")
    def reconcile_ramp_users(  # pylint: disable=too-many-branches,too-many-statements
        self, request: HttpRequest, queryset: QuerySet[Person]  # pylint: disable=unused-argument
    ) -> None:
        """
        Compare the list of Ramp users with OrgChart and identify any discrepancies.
        """
        ramp_users = get_ramp_users(get_ramp_access_token("users:read"))
        warnings = 0

        for ramp_user in ramp_users:
            try:
                local_user = Person.objects.get(ramp_user_id__iexact=ramp_user["id"])
            except Person.DoesNotExist:
                self.message_user(
                    request,
                    mark_safe(
                        '<a href="https://app.ramp.com/people/all/'
                        + ramp_user["id"]
                        + '">'
                        + ramp_user["first_name"]
                        + " "
                        + ramp_user["last_name"]
                        + "</a> has a Ramp account, but is not in OrgChart."
                    ),
                    messages.WARNING,
                )
                warnings += 1
                continue

            if local_user.is_active:
                if ramp_user["status"] != "USER_ACTIVE":
                    self.message_user(
                        request,
                        mark_safe(
                            '<a href="https://app.ramp.com/people/all/'
                            + ramp_user["id"]
                            + '">'
                            + ramp_user["first_name"]
                            + " "
                            + ramp_user["last_name"]
                            + "</a> has a Ramp account, but the status is "
                            + ramp_user["status"]
                            + "."
                        ),
                        messages.WARNING,
                    )
                    warnings += 1
                    continue
            elif ramp_user["status"] == "USER_ACTIVE":
                self.message_user(
                    request,
                    mark_safe(
                        '<a href="https://app.ramp.com/people/all/'
                        + ramp_user["id"]
                        + '">'
                        + ramp_user["first_name"]
                        + " "
                        + ramp_user["last_name"]
                        + '</a> has an active Ramp account, but they are not active in <a href="'
                        + reverse("admin:org_person_change", args=(local_user.id,))
                        + '">OrgChart</a>.'
                    ),
                    messages.WARNING,
                )
                warnings += 1
                continue

            if hasattr(local_user, "position"):
                this_position = local_user.position

                if (
                    this_position.reports_to_position is None
                    and ramp_user["manager_id"] is not None
                ):
                    current_manager_in_ramp = [
                        u for u in ramp_users if u["id"] == ramp_user["manager_id"]
                    ][0]

                    self.message_user(
                        request,
                        mark_safe(
                            '<a href="https://app.ramp.com/people/all/'
                            + ramp_user["id"]
                            + '">'
                            + ramp_user["first_name"]
                            + " "
                            + ramp_user["last_name"]
                            + "</a> should not have a manager in Ramp, but currently reports to "
                            + '<a href="https://app.ramp.com/people/all/'
                            + ramp_user["manager_id"]
                            + '">'
                            + current_manager_in_ramp["first_name"]
                            + " "
                            + current_manager_in_ramp["last_name"]
                            + "</a>."
                        ),
                        messages.WARNING,
                    )
                    warnings += 1
                    continue

                if this_position.reports_to_position is None and ramp_user["manager_id"] is None:
                    # user matches across Ramp and OrgChart
                    continue

                if this_position.reports_to_position.person is not None:
                    if this_position.reports_to_position.person.ramp_user_id is None:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="'
                                + reverse(
                                    "admin:org_person_change",
                                    args=(local_user.reports_to_position.person.id,),  # type: ignore  # noqa
                                )
                                + '">'
                                + str(local_user.reports_to_position.person)  # type: ignore
                                + "</a>, but "
                                + '<a href="'
                                + reverse(
                                    "admin:org_person_change",
                                    args=(local_user.reports_to_position.person.id,),  # type: ignore  # noqa
                                )
                                + '">'
                                + str(local_user.reports_to_position.person)  # type: ignore
                                + "</a> does not have a Ramp account."
                            ),
                            messages.WARNING,
                        )
                        warnings += 1
                        continue

                    if ramp_user["manager_id"] is None:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="https://app.ramp.com/people/all/'
                                + str(this_position.reports_to_position.person.ramp_user_id)
                                + '">'
                                + str(this_position.reports_to_position.person)
                                + "</a>, but does not have a manager in Ramp."
                            ),
                            messages.WARNING,
                        )
                        warnings += 1
                        continue

                    if (
                        uuid.UUID(ramp_user["manager_id"])
                        != this_position.reports_to_position.person.ramp_user_id
                    ):
                        current_manager_in_ramp = [
                            u for u in ramp_users if u["id"] == ramp_user["manager_id"]
                        ][0]

                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="https://app.ramp.com/people/all/'
                                + str(this_position.reports_to_position.person.ramp_user_id)
                                + '">'
                                + str(this_position.reports_to_position.person)
                                + "</a>, but currently reports to "
                                + '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["manager_id"]
                                + '">'
                                + current_manager_in_ramp["first_name"]
                                + " "
                                + current_manager_in_ramp["last_name"]
                                + "</a>."
                            ),
                            messages.WARNING,
                        )
                        warnings += 1
                        continue

            else:
                if local_user.reports_to_position is None:
                    if ramp_user["manager_id"] is not None:
                        current_manager_in_ramp = [
                            u for u in ramp_users if u["id"] == ramp_user["manager_id"]
                        ][0]

                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should not have a manager in Ramp, but currently reports to "  # noqa
                                + '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["manager_id"]
                                + '">'
                                + current_manager_in_ramp["first_name"]
                                + " "
                                + current_manager_in_ramp["last_name"]
                                + "</a>."
                            ),
                            messages.WARNING,
                        )
                        warnings += 1
                        continue

                else:
                    if local_user.reports_to_position.person is None:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="'
                                + reverse(
                                    "admin:org_position_change",
                                    args=(local_user.reports_to_position.id,),
                                )
                                + '">'
                                + str(local_user.reports_to_position)
                                + "</a>, but this position is vacant."
                            ),
                            messages.WARNING,
                        )
                        warnings += 1
                        continue

                    if local_user.reports_to_position.person.ramp_user_id is None:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="'
                                + reverse(
                                    "admin:org_person_change",
                                    args=(local_user.reports_to_position.person.id,),
                                )
                                + '">'
                                + str(local_user.reports_to_position.person)
                                + "</a>, but "
                                + '<a href="'
                                + reverse(
                                    "admin:org_person_change",
                                    args=(local_user.reports_to_position.person.id,),
                                )
                                + '">'
                                + str(local_user.reports_to_position.person)
                                + "</a> does not have a Ramp account."
                            ),
                            messages.WARNING,
                        )
                        warnings += 1
                        continue

                    if (
                        local_user.reports_to_position.person.ramp_user_id is not None
                        and ramp_user["manager_id"] is None
                    ):
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="https://app.ramp.com/people/all/'
                                + str(local_user.reports_to_position.person.ramp_user_id)
                                + '">'
                                + str(local_user.reports_to_position.person)
                                + "</a>, but does not have a manager in Ramp."
                            ),
                            messages.WARNING,
                        )
                        warnings += 1
                        continue

                    if local_user.reports_to_position.person.ramp_user_id != uuid.UUID(
                        ramp_user["manager_id"]
                    ):
                        current_manager_in_ramp = [
                            u for u in ramp_users if u["id"] == ramp_user["manager_id"]
                        ][0]

                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["id"]
                                + '">'
                                + ramp_user["first_name"]
                                + " "
                                + ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="https://app.ramp.com/people/all/'
                                + str(local_user.reports_to_position.person.ramp_user_id)
                                + '">'
                                + str(local_user.reports_to_position.person)
                                + "</a>, but currently reports to "
                                + '<a href="https://app.ramp.com/people/all/'
                                + ramp_user["manager_id"]
                                + '">'
                                + current_manager_in_ramp["first_name"]
                                + " "
                                + current_manager_in_ramp["last_name"]
                                + "</a>."
                            ),
                            messages.WARNING,
                        )
                        warnings += 1

        if warnings == 0:
            self.message_user(
                request,
                "All Ramp users match OrgChart.",
                messages.SUCCESS,
            )

    @admin.action(permissions=["change"], description="Reconcile Google Workspace users")
    def reconcile_google_workspace_users(  # pylint: disable=too-many-branches
        self, request: HttpRequest, queryset: QuerySet[Person]  # pylint: disable=unused-argument
    ) -> None:
        """
        Compare the list of Google Workspace users with OrgChart and identify any discrepancies.
        """
        workspace_users = get_google_workspace_users()
        updated_workspace_user_id_count = 0
        added_new_person_count = 0
        warnings = 0

        keycloak_token = get_keycloak_access_token()

        for workspace_user in workspace_users:
            try:
                local_user = Person.objects.get(
                    google_workspace_user_id__iexact=workspace_user["id"]
                )

                if not workspace_user["suspended"] and not local_user.is_active:
                    self.message_user(
                        request,
                        mark_safe(
                            '<a href="https://www.google.com/a/robojackets.org/ServiceLogin?continue=https://admin.google.com/ac/search?query='  # noqa
                            + workspace_user["primaryEmail"]
                            + '&tab=USERS">'
                            + workspace_user["name"]["fullName"]
                            + '</a> has an active Google Workspace account, but they are not active in <a href="'  # noqa
                            + reverse("admin:org_person_change", args=(local_user.id,))
                            + '">OrgChart</a>.'
                        ),
                        messages.WARNING,
                    )
                    warnings += 1

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
                        "Failed to search Keycloak for Google Workspace user: "
                        + keycloak_user_search.text
                    ) from exc

                if len(keycloak_user_search.json()) == 0:
                    if not workspace_user["suspended"]:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://www.google.com/a/robojackets.org/ServiceLogin?continue=https://admin.google.com/ac/search?query='  # noqa
                                + workspace_user["primaryEmail"]
                                + '&tab=USERS">'
                                + workspace_user["name"]["fullName"]
                                + "</a> has an active Google Workspace account, but does not have a corresponding account in Keycloak."  # noqa
                            ),
                            messages.WARNING,
                        )

                        warnings += 1

                    continue

                if len(keycloak_user_search.json()) > 1:
                    raise Exception(
                        "Keycloak search returned multiple results for Google Workspace user "
                        + workspace_user["primaryEmail"]
                    ) from exc

                keycloak_user = keycloak_user_search.json()[0]

                try:
                    local_user = Person.objects.get(username__iexact=keycloak_user["username"])

                    local_user.google_workspace_user_id = workspace_user["id"]
                    local_user.save()

                    if not workspace_user["suspended"] and not local_user.is_active:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://www.google.com/a/robojackets.org/ServiceLogin?continue=https://admin.google.com/ac/search?query='  # noqa
                                + workspace_user["primaryEmail"]
                                + '&tab=USERS">'
                                + workspace_user["name"]["fullName"]
                                + '</a> has an active Google Workspace account, but they are not active in <a href="'  # noqa
                                + reverse("admin:org_person_change", args=(local_user.id,))
                                + '">OrgChart</a>.'
                            ),
                            messages.WARNING,
                        )
                        warnings += 1

                    updated_workspace_user_id_count += 1
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

                    if not workspace_user["suspended"] and not local_user.is_active:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://www.google.com/a/robojackets.org/ServiceLogin?continue=https://admin.google.com/ac/search?query='  # noqa
                                + workspace_user["primaryEmail"]
                                + '&tab=USERS">'
                                + workspace_user["name"]["fullName"]
                                + '</a> has an active Google Workspace account, but they are not active in <a href="'  # noqa
                                + reverse("admin:org_person_change", args=(local_user.id,))
                                + '">OrgChart</a>.'
                            ),
                            messages.WARNING,
                        )
                        warnings += 1

                    added_new_person_count += 1

        if updated_workspace_user_id_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Updated Google Workspace user ID for %d person.",
                    "Updated Google Workspace user IDs for %d people.",
                    updated_workspace_user_id_count,
                )
                % updated_workspace_user_id_count,
                messages.SUCCESS,
            )

        if added_new_person_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Added %d person.",
                    "Added %d people.",
                    added_new_person_count,
                )
                % added_new_person_count,
                messages.SUCCESS,
            )

        if warnings == 0:
            self.message_user(
                request,
                "All Google Workspace users match OrgChart.",
                messages.SUCCESS,
            )

    @admin.action(permissions=["change"], description="Reconcile HubSpot users")
    def reconcile_hubspot_users(  # pylint: disable=too-many-branches,too-many-locals
        self, request: HttpRequest, queryset: QuerySet[Person]  # pylint: disable=unused-argument
    ) -> None:
        """
        Compare the list of HubSpot users with OrgChart and identify any discrepancies.
        """

        hubspot = HubSpot(access_token=settings.HUBSPOT_ACCESS_TOKEN)
        hubspot_portal_id = str(
            hubspot.api_request(
                {
                    "path": "/account-info/v3/details",
                }
            ).json()["portalId"]
        )
        hubspot_users = hubspot.settings.users.users_api.get_page().results

        updated_hubspot_user_id_count = 0
        added_new_person_count = 0
        warnings = 0

        keycloak_token = get_keycloak_access_token()

        for hubspot_user in hubspot_users:
            try:
                local_user = Person.objects.get(hubspot_user_id__iexact=hubspot_user.id)

                if not local_user.is_active:
                    self.message_user(
                        request,
                        mark_safe(
                            '<a href="https://app.hubspot.com/settings/'
                            + hubspot_portal_id
                            + "/users/user/"  # noqa
                            + hubspot_user.id
                            + '">'
                            + str(local_user)
                            + '</a> has a HubSpot account, but they are not active in <a href="'  # noqa
                            + reverse("admin:org_person_change", args=(local_user.id,))
                            + '">OrgChart</a>.'
                        ),
                        messages.WARNING,
                    )
                    warnings += 1

            except Person.DoesNotExist as exc:
                # determine if this hubspot user is in keycloak
                keycloak_user_search = get(
                    url=settings.KEYCLOAK_SERVER + "/admin/realms/robojackets/users",
                    headers={
                        "Authorization": "Bearer " + keycloak_token,
                        "Accept": "application/json",
                    },
                    params={
                        "q": "googleWorkspaceAccount:" + hubspot_user.email,
                    },
                    timeout=(5, 5),
                )

                if keycloak_user_search.status_code != 200:
                    raise Exception(
                        "Failed to search Keycloak for HubSpot user: " + keycloak_user_search.text
                    ) from exc

                if len(keycloak_user_search.json()) == 0:
                    self.message_user(
                        request,
                        mark_safe(
                            '<a href="https://app.hubspot.com/settings/'
                            + hubspot_portal_id
                            + "/users/user/"  # noqa
                            + hubspot_user.id
                            + '">'
                            + hubspot_user.email
                            + "</a> has a HubSpot account, but does not have a corresponding account in Keycloak."  # noqa
                        ),
                        messages.WARNING,
                    )

                    warnings += 1

                    continue

                if len(keycloak_user_search.json()) > 1:
                    raise Exception(
                        "Keycloak search returned multiple results for HubSpot user "
                        + hubspot_user.email
                    ) from exc

                keycloak_user = keycloak_user_search.json()[0]

                try:
                    local_user = Person.objects.get(username__iexact=keycloak_user["username"])

                    local_user.hubspot_user_id = hubspot_user.id
                    local_user.save()

                    if not local_user.is_active:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.hubspot.com/settings/'
                                + hubspot_portal_id
                                + "/users/user/"  # noqa
                                + hubspot_user.id
                                + '">'
                                + str(local_user)
                                + '</a> has a HubSpot account, but they are not active in <a href="'  # noqa
                                + reverse("admin:org_person_change", args=(local_user.id,))
                                + '">OrgChart</a>.'
                            ),
                            messages.WARNING,
                        )
                        warnings += 1

                    updated_hubspot_user_id_count += 1
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
                        first_name=keycloak_user["firstName"],
                        last_name=keycloak_user["lastName"],
                        keycloak_user_id=keycloak_user["id"],
                        ramp_user_id=this_ramp_user_id,
                        hubspot_user_id=hubspot_user.id,
                        is_active=keycloak_user["enabled"],
                        is_staff=settings.DEBUG,
                        is_superuser=settings.DEBUG,
                    )

                    if not local_user.is_active:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.hubspot.com/settings/'
                                + hubspot_portal_id
                                + "/users/user/"  # noqa
                                + hubspot_user.id
                                + '">'
                                + str(local_user)
                                + '</a> has a HubSpot account, but they are not active in <a href="'  # noqa
                                + reverse("admin:org_person_change", args=(local_user.id,))
                                + '">OrgChart</a>.'
                            ),
                            messages.WARNING,
                        )
                        warnings += 1

                    added_new_person_count += 1

        if updated_hubspot_user_id_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Updated HubSpot user ID for %d person.",
                    "Updated HubSpot user IDs for %d people.",
                    updated_hubspot_user_id_count,
                )
                % updated_hubspot_user_id_count,
                messages.SUCCESS,
            )

        if added_new_person_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Added %d person.",
                    "Added %d people.",
                    added_new_person_count,
                )
                % added_new_person_count,
                messages.SUCCESS,
            )

        if warnings == 0:
            self.message_user(
                request,
                "All HubSpot users match OrgChart.",
                messages.SUCCESS,
            )


class PositionAdmin(admin.ModelAdmin):  # type: ignore
    """
    Model admin configuration for Position
    """

    fieldsets = (
        (None, {"fields": ("name",)}),
        ("Team", {"fields": ("manages_apiary_team", "member_of_apiary_team")}),
        ("Organization hierarchy", {"fields": ("reports_to_position",)}),
        ("Person", {"fields": ("person",)}),
    )
    list_display = [
        "name",
        "manages_apiary_team",
        "member_of_apiary_team",
        "reports_to_position",
        "person",
    ]
    list_filter = ("name", "member_of_apiary_team", "reports_to_position")
    search_fields = (
        "name",
        "person__username",
        "person__first_name",
        "person__last_name",
        "person__email",
    )
    autocomplete_fields = ("person",)
    inlines = (InlinePersonAdmin, ReportsToPositionAdmin)

    def get_inline_instances(self, request, obj=None) -> List[InlineModelAdmin]:  # type: ignore
        return (  # pylint: disable=simplify-boolean-expression
            obj and super().get_inline_instances(request, obj) or []
        )

    def changelist_view(
        self, request: HttpRequest, extra_context: Dict[str, Any] | None = None
    ) -> HttpResponse:
        if "action" in request.POST and request.POST["action"] in ("fetch_positions_from_apiary",):
            r = request.POST.copy()
            for p in Person.objects.all():
                r.update({ACTION_CHECKBOX_NAME: str(p.id)})
            request.POST = r  # type: ignore
        return super().changelist_view(request, extra_context)

    def save_model(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        self, request: HttpRequest, obj: Position, form: Any, change: Any
    ) -> None:
        super().save_model(request, obj, form, change)

        position = obj

        new_project_manager_id = None

        if position.person is not None:
            update_google_workspace_user.delay_on_commit(position.person.id)  # type: ignore

            if position.person.apiary_user_id is None:
                return

            new_project_manager_id = position.person.apiary_user_id

        apiary_team_id = position.manages_apiary_team

        if apiary_team_id is not None:  # pylint: disable=too-many-nested-blocks
            get_team_response = get(
                url=settings.APIARY_SERVER + "/api/v1/teams/" + str(apiary_team_id),
                headers={
                    "Authorization": "Bearer " + settings.APIARY_TOKEN,
                    "Accept": "application/json",
                },
                timeout=(5, 5),
                params={
                    "include": "projectManager",
                },
            )

            if get_team_response.status_code != 200:
                self.message_user(
                    request,
                    mark_safe(
                        'Failed to update manager for <a href="https://my.robojackets.org/nova/resources/teams/'  # noqa
                        + str(apiary_team_id)
                        + '">'
                        + get_teams()[apiary_team_id]
                        + "</a> in Apiary: "
                        + get_team_response.text
                    ),
                    messages.WARNING,
                )
                return

            if "team" not in get_team_response.json() or get_team_response.json()["team"] is None:
                self.message_user(
                    request,
                    mark_safe(
                        'Failed to update manager for <a href="https://my.robojackets.org/nova/resources/teams/'  # noqa
                        + str(apiary_team_id)
                        + '">'
                        + get_teams()[apiary_team_id]
                        + "</a> in Apiary: "
                        + get_team_response.text
                    ),
                    messages.WARNING,
                )
                return

            current_project_manager_id = None

            if (
                "project_manager" in get_team_response.json()["team"]
                and get_team_response.json()["team"]["project_manager"] is not None
                and "id" in get_team_response.json()["team"]["project_manager"]
                and get_team_response.json()["team"]["project_manager"]["id"] is not None
            ):
                current_project_manager_id = get_team_response.json()["team"]["project_manager"][
                    "id"
                ]

            if current_project_manager_id != new_project_manager_id:
                cache.clear()
                update_team_response = patch(
                    url=settings.APIARY_SERVER + "/api/v1/teams/" + str(apiary_team_id),
                    headers={
                        "Authorization": "Bearer " + settings.APIARY_TOKEN,
                        "Accept": "application/json",
                    },
                    timeout=(5, 5),
                    json={
                        "project_manager_id": new_project_manager_id,
                    },
                )

                if update_team_response.status_code == 201:
                    self.message_user(
                        request,
                        mark_safe(
                            'Updated manager for <a href="https://my.robojackets.org/nova/resources/teams/'  # noqa
                            + str(update_team_response.json()["team"]["id"])
                            + '">'
                            + update_team_response.json()["team"]["name"]
                            + "</a> in Apiary."
                        ),
                        messages.SUCCESS,
                    )
                else:
                    self.message_user(
                        request,
                        mark_safe(
                            'Failed to update manager for <a href="https://my.robojackets.org/nova/resources/teams/'  # noqa
                            + str(apiary_team_id)
                            + '">'
                            + get_teams()[apiary_team_id]
                            + "</a> in Apiary: "
                            + update_team_response.text
                        ),
                        messages.WARNING,
                    )

                possible_prior_project_managers = Person.objects.filter(
                    member_of_apiary_team__exact=apiary_team_id, manual_hierarchy__exact=False
                ).exclude(reports_to_position__exact=position)

                for person in possible_prior_project_managers:
                    update_google_workspace_user.delay_on_commit(person.id)  # type: ignore

                    apiary_user = get_apiary_user(person.username)

                    if apiary_user is None:
                        if person.is_active:
                            person.is_active = False
                            person.save()

                            self.message_user(
                                request,
                                mark_safe(
                                    '<a href="'
                                    + reverse("admin:org_person_change", args=(person.id,))
                                    + '">'
                                    + str(person)
                                    + "</a> was not found in Apiary, and was therefore deactivated in OrgChart."  # noqa
                                ),
                                messages.WARNING,
                            )

                            return

                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="'
                                + reverse("admin:org_person_change", args=(person.id,))
                                + '">'
                                + str(person)
                                + "</a> was not found in Apiary."
                            ),
                            messages.WARNING,
                        )
                        return

                    if person.is_active != apiary_user["is_access_active"]:
                        person.is_active = apiary_user["is_access_active"]
                        self.message_user(
                            request,
                            mark_safe(
                                'Updated active status for <a href="'
                                + reverse("admin:org_person_change", args=(person.id,))
                                + '">'
                                + str(person)
                                + "</a>."
                            ),
                            messages.SUCCESS,
                        )

                    if not person.manual_hierarchy:
                        if (
                            "primary_team" in apiary_user
                            and apiary_user["primary_team"] is not None
                            and "id" in apiary_user["primary_team"]
                            and apiary_user["primary_team"]["id"] is not None
                        ):
                            apiary_primary_team_id = apiary_user["primary_team"]["id"]

                            if person.member_of_apiary_team != apiary_primary_team_id:
                                person.member_of_apiary_team = apiary_primary_team_id
                                self.message_user(
                                    request,
                                    mark_safe(
                                        'Updated primary team for <a href="'
                                        + reverse("admin:org_person_change", args=(person.id,))
                                        + '">'
                                        + str(person)
                                        + '</a> to <a href="https://my.robojackets.org/nova/resources/teams/'  # noqa
                                        + str(apiary_primary_team_id)
                                        + '">'
                                        + get_teams()[apiary_primary_team_id]
                                        + "</a>."
                                    ),
                                    messages.SUCCESS,
                                )

                        if (
                            "manager" in apiary_user
                            and apiary_user["manager"] is not None
                            and "id" in apiary_user["manager"]
                            and apiary_user["manager"]["id"] is not None
                        ):
                            try:
                                person_reports_to_position = Position.objects.get(
                                    person=Person.objects.get(
                                        apiary_user_id__exact=apiary_user["manager"]["id"]
                                    )
                                )

                                if person.reports_to_position != person_reports_to_position:
                                    person.reports_to_position = person_reports_to_position
                                    self.message_user(
                                        request,
                                        mark_safe(
                                            'Updated reporting position for <a href="'
                                            + reverse("admin:org_person_change", args=(person.id,))
                                            + '">'
                                            + str(person)
                                            + '</a> to <a href="'
                                            + reverse(
                                                "admin:org_position_change",
                                                args=(person_reports_to_position.id,),
                                            )
                                            + '">'
                                            + str(person_reports_to_position)
                                            + "</a>."
                                        ),
                                        messages.SUCCESS,
                                    )

                            except Position.DoesNotExist:
                                pass
                            except Person.DoesNotExist:
                                pass

                    if person.apiary_user_id is None:
                        person.apiary_user_id = apiary_user["id"]
                        self.message_user(
                            request,
                            mark_safe(
                                'Updated Apiary user ID for <a href="'
                                + reverse("admin:org_person_change", args=(person.id,))
                                + '">'
                                + str(person)
                                + "</a>."
                            ),
                            messages.SUCCESS,
                        )
                    elif person.apiary_user_id != apiary_user["id"]:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="'
                                + reverse("admin:org_person_change", args=(person.id,))
                                + '">'
                                + str(person)
                                + "</a> has an Apiary user ID within OrgChart, but it does not match their actual Apiary user ID."  # noqa
                                # noqa
                            ),
                            messages.WARNING,
                        )

                    person.save()

        ramp_token = get_ramp_access_token("users:read users:write")

        if position.person is not None:
            if position.person.ramp_user_id is not None:
                position_person_ramp_user = get_ramp_user(
                    str(position.person.ramp_user_id), ramp_token
                )

                if (
                    position.reports_to_position is None
                    and position_person_ramp_user["manager_id"] is not None
                ):
                    self.message_user(
                        request,
                        mark_safe(
                            '<a href="https://app.ramp.com/people/all/'  # noqa
                            + position_person_ramp_user["id"]
                            + '">'
                            + str(position.person)
                            + "</a> should not have a manager in Ramp, because "
                            + '<a href="'
                            + reverse("admin:org_position_change", args=(position.id,))
                            + '">'
                            + str(position)
                            + "</a> does not have a reporting position, however managers cannot be cleared via API. Update this person manually in Ramp if needed."  # noqa
                        ),
                        messages.WARNING,
                    )

                if position.reports_to_position is not None:
                    if position.reports_to_position.person is None:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + position_person_ramp_user["id"]
                                + '">'
                                + position_person_ramp_user["first_name"]
                                + " "
                                + position_person_ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="'
                                + reverse(
                                    "admin:org_position_change",
                                    args=(position.reports_to_position.id,),
                                )
                                + '">'
                                + str(position.reports_to_position)
                                + "</a> in Ramp, but this position is vacant."
                            ),
                            messages.WARNING,
                        )
                    elif position.reports_to_position.person.ramp_user_id is None:
                        self.message_user(
                            request,
                            mark_safe(
                                '<a href="https://app.ramp.com/people/all/'
                                + position_person_ramp_user["id"]
                                + '">'
                                + position_person_ramp_user["first_name"]
                                + " "
                                + position_person_ramp_user["last_name"]
                                + "</a> should report to "
                                + '<a href="'
                                + reverse(
                                    "admin:org_person_change",
                                    args=(position.reports_to_position.person.id,),
                                )
                                + '">'
                                + str(position.reports_to_position.person)
                                + "</a> in Ramp, but "
                                + '<a href="'
                                + reverse(
                                    "admin:org_person_change",
                                    args=(position.reports_to_position.person.id,),
                                )
                                + '">'
                                + str(position.reports_to_position.person)
                                + "</a> does not have a Ramp account."
                            ),
                            messages.WARNING,
                        )
                    elif position_person_ramp_user[
                        "manager_id"
                    ] is None or position.reports_to_position.person.ramp_user_id != uuid.UUID(
                        position_person_ramp_user["manager_id"]
                    ):
                        update_ramp_manager(
                            position_person_ramp_user["id"],
                            str(position.reports_to_position.person.ramp_user_id),
                            ramp_token,
                        )

                        self.message_user(
                            request,
                            mark_safe(
                                'Updated manager for <a href="https://app.ramp.com/people/all/'  # noqa
                                + position_person_ramp_user["id"]
                                + '">'
                                + str(position.person)
                                + '</a> to <a href="https://app.ramp.com/people/all/'
                                + str(position.reports_to_position.person.ramp_user_id)
                                + '">'
                                + str(position.reports_to_position.person)
                                + "</a> in Ramp."
                            ),
                            messages.SUCCESS,
                        )

            users_to_update = 0

            ramp_users = get_ramp_users(ramp_token)

            for ramp_user in ramp_users:
                try:
                    local_user = Person.objects.get(ramp_user_id__iexact=ramp_user["id"])
                except Person.DoesNotExist:
                    continue

                if (
                    hasattr(local_user, "position")
                    and local_user.position.reports_to_position == position
                ):
                    update_google_workspace_user.delay_on_commit(local_user.id)  # type: ignore

                    if position.person.ramp_user_id is None:
                        users_to_update += 1
                    else:
                        update_ramp_manager(
                            ramp_user["id"], str(position.person.ramp_user_id), ramp_token
                        )

                        self.message_user(
                            request,
                            mark_safe(
                                'Updated manager for <a href="https://app.ramp.com/people/all/'  # noqa
                                + ramp_user["id"]
                                + '">'
                                + str(local_user)
                                + '</a> to <a href="https://app.ramp.com/people/all/'
                                + str(position.person.ramp_user_id)
                                + '">'
                                + str(position.person)
                                + "</a> in Ramp."
                            ),
                            messages.SUCCESS,
                        )
                elif (
                    not hasattr(local_user, "position")
                    and local_user.reports_to_position == position
                ):
                    update_google_workspace_user.delay_on_commit(local_user.id)  # type: ignore

                    if position.person.ramp_user_id is None:
                        users_to_update += 1
                    elif ramp_user["manager_id"] != str(position.person.ramp_user_id):
                        update_ramp_manager(
                            ramp_user["id"], str(position.person.ramp_user_id), ramp_token
                        )

                        self.message_user(
                            request,
                            mark_safe(
                                'Updated manager for <a href="https://app.ramp.com/people/all/'  # noqa
                                + ramp_user["id"]
                                + '">'
                                + str(local_user)
                                + '</a> to <a href="https://app.ramp.com/people/all/'
                                + str(position.person.ramp_user_id)
                                + '">'
                                + str(position.person)
                                + "</a> in Ramp."
                            ),
                            messages.SUCCESS,
                        )

            if users_to_update > 0:
                self.message_user(
                    request,
                    mark_safe(
                        ngettext(
                            "%d person reports to this position, but can't be updated in Ramp, because "  # noqa
                            + '<a href="'
                            + reverse("admin:org_person_change", args=(position.person.id,))
                            + '">'
                            + str(position.person)
                            + "</a> doesn't have a Ramp account.",
                            "%d people report to this position, but can't be updated in Ramp, because "  # noqa
                            + '<a href="'
                            + reverse("admin:org_person_change", args=(position.person.id,))
                            + '">'
                            + str(position.person)
                            + "</a> doesn't have a Ramp account.",
                            users_to_update,
                        )
                        % users_to_update
                    ),
                    messages.WARNING,
                )

    actions = [
        "fetch_positions_from_apiary",
    ]

    @admin.action(permissions=["add"], description="Fetch positions from Apiary")
    def fetch_positions_from_apiary(  # pylint: disable=too-many-branches,too-many-locals
        self, request: HttpRequest, queryset: QuerySet[Position]  # pylint: disable=unused-argument
    ) -> None:
        """
        Fetch team information from Apiary and create positions for managers
        """
        added_new_person_count = 0
        added_new_position_count = 0
        apiary_id_reports_to_apiary_id = {}
        count_apiary_ids_reporting_to_apiary_id: Dict[int, int] = defaultdict(int)

        teams_response = get(
            url=settings.APIARY_SERVER + "/api/v1/teams",
            headers={
                "Authorization": "Bearer " + settings.APIARY_TOKEN,
                "Accept": "application/json",
            },
            params={
                "include": "projectManager",
            },
            timeout=(5, 5),
        )

        if teams_response.status_code != 200:
            raise Exception("Unable to fetch positions from Apiary: " + teams_response.text)

        if "teams" not in teams_response.json():
            raise Exception("Unable to fetch positions from Apiary: " + teams_response.text)

        for team in teams_response.json()["teams"]:
            if (
                "project_manager" in team
                and team["project_manager"] is not None
                and "id" in team["project_manager"]
                and team["project_manager"]["id"] is not None
            ):
                this_team_project_manager, users_created_this_call = (
                    find_or_create_local_user_for_apiary_user_id(team["project_manager"]["id"])
                )
                added_new_person_count += users_created_this_call

                try:
                    Position.objects.get(manages_apiary_team__exact=team["id"])
                except Position.DoesNotExist:
                    try:
                        Position.objects.get(person=this_team_project_manager)
                    except Position.DoesNotExist:
                        this_position = Position(
                            manages_apiary_team=team["id"],
                            member_of_apiary_team=team["id"],
                            name="Project Manager",
                            person=this_team_project_manager,
                        )
                        this_position.save()

                        apiary_user = get_apiary_user(str(team["project_manager"]["id"]))

                        if apiary_user is None:
                            continue

                        if (
                            "manager" in apiary_user
                            and apiary_user["manager"] is not None
                            and "id" in apiary_user["manager"]
                            and apiary_user["manager"]["id"] is not None
                        ):
                            apiary_id_reports_to_apiary_id[team["project_manager"]["id"]] = (
                                apiary_user["manager"]["id"]
                            )
                            count_apiary_ids_reporting_to_apiary_id[
                                apiary_user["manager"]["id"]
                            ] += 1

                        added_new_position_count += 1

        # any teams or project managers that were previously missing have been added
        # try to derive hierarchy for positions that were just added
        for direct_report, manager in apiary_id_reports_to_apiary_id.items():
            # break loops
            if (
                apiary_id_reports_to_apiary_id[manager] == direct_report
                and count_apiary_ids_reporting_to_apiary_id[direct_report]
                > count_apiary_ids_reporting_to_apiary_id[manager]
            ):
                continue

            try:
                direct_report_position = Position.objects.get(
                    person=Person.objects.get(apiary_user_id__exact=direct_report)
                )
                manager_position = Position.objects.get(
                    person=Person.objects.get(apiary_user_id__exact=manager)
                )

                direct_report_position.reports_to_position = manager_position
                direct_report_position.save()
            except Position.DoesNotExist:
                pass
            except Person.DoesNotExist:
                pass

        if added_new_person_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Added %d person.",
                    "Added %d people.",
                    added_new_person_count,
                )
                % added_new_person_count,
                messages.SUCCESS,
            )

        if added_new_position_count > 0:
            self.message_user(
                request,
                ngettext(
                    "Added %d position.",
                    "Added %d positions.",
                    added_new_position_count,
                )
                % added_new_position_count,
                messages.SUCCESS,
            )

        if added_new_person_count == 0 and added_new_position_count == 0:
            self.message_user(
                request,
                "No changes made.",
                messages.SUCCESS,
            )


admin.site.register(Person, PersonAdmin)
admin.site.register(Position, PositionAdmin)
