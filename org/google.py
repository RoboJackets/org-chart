from typing import List, Dict

import googleapiclient  # type: ignore
from django.conf import settings
from google.oauth2 import service_account
from googleapiclient.discovery import build  # type: ignore


def get_google_workspace_client() -> googleapiclient.discovery.Resource:
    """
    Get a Google Workspace API client for manipulating users.
    """
    credentials = service_account.Credentials.from_service_account_info(  # type: ignore
        info=settings.GOOGLE_SERVICE_ACCOUNT_CREDENTIALS,
        scopes=["https://www.googleapis.com/auth/admin.directory.user"],
        subject=settings.GOOGLE_SUBJECT,
    )

    directory = build(serviceName="admin", version="directory_v1", credentials=credentials)

    return directory.users()


def get_google_workspace_users() -> List[Dict]:  # type: ignore
    """
    Get all users in the Google Workspace customer.
    """
    users = get_google_workspace_client()

    request = users.list(customer="my_customer")

    all_users = []

    while request is not None:
        response = request.execute()

        all_users.extend(response["users"])

        request = users.list_next(request, response)

    return all_users
