from django.db import models
from django.contrib.auth.models import AbstractUser

from org.apiary import get_teams


class Position(models.Model):
    """
    A position is an elected or appointed office, such as president, treasurer, or project manager
    """

    name = models.CharField(
        max_length=100,
        verbose_name="Short title",
        help_text="The short-form title of this position, not including a team name.",
    )
    manages_apiary_team = models.IntegerField(
        null=True,
        blank=True,
        choices=get_teams,
        unique=True,
        verbose_name="Manages team",
        help_text="If this position is the primary leader for a team, select it here. Only one position can be the team manager.",  # noqa
    )
    member_of_apiary_team = models.IntegerField(
        choices=get_teams,
        verbose_name="Primary team",
        help_text="The primary team this position supports.",
    )
    reports_to_position = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, verbose_name="Reports to"
    )
    person = models.OneToOneField(
        "Person", null=True, blank=True, on_delete=models.CASCADE, unique=True
    )

    def __str__(self) -> str:
        return get_teams()[self.member_of_apiary_team] + " " + self.name

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("name", "member_of_apiary_team"), name="unique_name_within_team"
            ),
        ]


class Person(AbstractUser):
    """
    A person is a human who may or may not be occupying a position
    """

    apiary_user_id = models.IntegerField(
        null=True, blank=True, unique=True, verbose_name="Apiary user ID"
    )
    ramp_user_id = models.UUIDField(null=True, blank=True, unique=True, verbose_name="Ramp user ID")
    keycloak_user_id = models.UUIDField(
        null=True, blank=True, unique=True, verbose_name="Keycloak user ID"
    )
    google_workspace_user_id = models.CharField(
        null=True, blank=True, max_length=100, unique=True, verbose_name="Google Workspace user ID"
    )
    hubspot_user_id = models.IntegerField(null=True, blank=True, unique=True, verbose_name="HubSpot user ID")
    slack_user_id = models.CharField(null=True, blank=True, max_length=9, unique=True)
    reports_to_position = models.ForeignKey(
        "Position",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="direct_reports",
        verbose_name="Reports to",
        help_text="If this person is in a position, the reporting position for their position will take precedence.",  # noqa
    )
    member_of_apiary_team = models.IntegerField(
        null=True,
        blank=True,
        choices=get_teams,
        verbose_name="Primary team",
        help_text="If this person is in a position, the primary team for their position will take precedence.",  # noqa
    )
    title = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Short title",
        help_text="If this person has a one-off title or a title shared with multiple people, you can set it here instead of using a position. If this person is in a position, the position title will take precedence.",  # noqa
    )
    manual_hierarchy = models.BooleanField(
        default=False,
        help_text="Designates whether the reporting position or primary team have been set manually. Both values may be automatically changed based on Apiary data if this is not enabled.",  # noqa
    )

    def __str__(self) -> str:
        return self.first_name + " " + self.last_name

    class Meta:
        verbose_name_plural = "people"
