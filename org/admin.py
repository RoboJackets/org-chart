from typing import Literal, List

from django.contrib import admin
from django.contrib.admin.options import InlineModelAdmin
from django.contrib.auth.admin import UserAdmin

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
