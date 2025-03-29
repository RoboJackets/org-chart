from typing import Dict, List

from django.conf import settings
from mozilla_django_oidc.auth import OIDCAuthenticationBackend  # type: ignore

from org.models import Person


class AuthenticationBackend(OIDCAuthenticationBackend):  # type: ignore
    """
    Maps Keycloak claims to Django user fields
    """

    def filter_users_by_claims(self, claims: Dict[str, str]) -> List[Person]:
        username = claims.get("preferred_username")
        if not username:
            return self.UserModel.objects.none()  # type: ignore

        try:
            return [Person.objects.get(username=username)]

        except Person.DoesNotExist:  # pylint: disable=no-member
            return self.UserModel.objects.none()  # type: ignore

    def create_user(self, claims: Dict[str, str]) -> Person:
        user = Person.objects.create_user(
            username=claims["preferred_username"],
            email=claims["email"],
            password=None,
            first_name=claims["given_name"],
            last_name=claims["family_name"],
            keycloak_user_id=claims["sub"],
            ramp_user_id=claims.get("ramp_user_id", None),
            is_active=True,
            is_staff=settings.DEBUG,
            is_superuser=settings.DEBUG,
        )

        return user

    def update_user(self, user: Person, claims: Dict[str, str]) -> Person:
        user.first_name = claims.get("given_name", "")
        user.last_name = claims.get("family_name", "")
        user.email = claims.get("email", "")
        user.keycloak_user_id = claims.get("sub")
        user.ramp_user_id = claims.get("ramp_user_id", None)
        user.save()

        return user
