import uuid

from django.core.exceptions import BadRequest
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from orgchart.tasks import import_ramp_user, import_google_workspace_user


class ImportRampUser(APIView):
    """
    Import a Ramp user by ID
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request) -> Response:
        """
        Import a Ramp user by ID
        """
        if "ramp_user_id" not in request.data:
            raise BadRequest("ramp_user_id is required")

        try:
            user_id = uuid.UUID(request.data["ramp_user_id"])
        except ValueError as e:
            raise BadRequest("ramp_user_id is not a valid UUID") from e

        import_ramp_user.delay(str(user_id))

        return Response(data={"status": "accepted"}, status=202)


class ImportGoogleWorkspaceUser(APIView):
    """
    Import a Google Workspace user by ID
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request) -> Response:
        """
        Import a Google Workspace user by ID
        """
        if "google_workspace_user_id" not in request.data:
            raise BadRequest("google_workspace_user_id is required")

        if not request.data["google_workspace_user_id"].isdigit():
            raise BadRequest("google_workspace_user_id is not numeric")

        import_google_workspace_user.delay(request.data["google_workspace_user_id"])

        return Response(data={"status": "accepted"}, status=202)
