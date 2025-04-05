from gettext import ngettext
from typing import Literal, List, Dict, Any

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.admin.options import InlineModelAdmin
from django.contrib.auth.admin import UserAdmin
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from requests import post, get

from .models import Person, Position


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


class PersonAdmin(UserAdmin):  # type: ignore
    """
    Model admin configuration for Person
    """

    fieldsets = (
        (None, {"fields": ("username",)}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        ("Linked accounts", {"fields": ("apiary_user_id", "keycloak_user_id", "ramp_user_id")}),
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
        if "action" in request.POST and request.POST["action"] == "fetch_users_from_keycloak":
            r = request.POST.copy()
            for p in Person.objects.all():
                r.update({ACTION_CHECKBOX_NAME: str(p.id)})
            request.POST = r  # type: ignore
        return super().changelist_view(request, extra_context)

    actions = [
        "fetch_users_from_keycloak",
    ]

    @admin.action(permissions=["add"], description="Fetch people from Keycloak")
    def fetch_users_from_keycloak(
        self, request: HttpRequest, queryset: QuerySet[Person]  # pylint: disable=unused-argument
    ) -> None:
        """
        Fetch user information from Keycloak and update or create local users as needed
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
            self.message_user(
                request,
                "Error retrieving Keycloak access token: " + keycloak_access_token_response.text,
                messages.ERROR,
            )
            return

        keycloak_user_list_response = get(
            url=settings.KEYCLOAK_SERVER + "/admin/realms/robojackets/users",
            headers={
                "Authorization": "Bearer "
                + keycloak_access_token_response.json().get("access_token"),
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
            except Person.DoesNotExist:  # pylint: disable=no-member
                try:
                    this_person = Person.objects.get(username__iexact=keycloak_user["username"])
                    this_person.keycloak_user_id = keycloak_user["id"]
                    updated_keycloak_user_id_count += 1
                except Person.DoesNotExist:  # pylint: disable=no-member
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
    inlines = (InlinePersonAdmin, ReportsToPositionAdmin)

    def get_inline_instances(self, request, obj=None) -> List[InlineModelAdmin]:  # type: ignore
        return (  # pylint: disable=simplify-boolean-expression
            obj and super().get_inline_instances(request, obj) or []
        )


admin.site.register(Person, PersonAdmin)
admin.site.register(Position, PositionAdmin)
