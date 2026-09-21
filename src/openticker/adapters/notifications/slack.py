"""SlackAdapter(NotificationPort): posts to a Slack Incoming Webhook. No bot
token or OAuth app needed; the webhook URL decides the channel."""

from http import HTTPStatus

import httpx


class NotificationError(Exception):
    """A notification channel rejected or failed to deliver a message."""


class SlackAdapter:
    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    def send(self, subject: str, message: str) -> None:
        response = httpx.post(
            self._webhook_url, json={"text": f"*{subject}*\n{message}"}, timeout=10.0
        )
        if response.status_code >= HTTPStatus.BAD_REQUEST:
            # The webhook URL is itself a secret; never include it in the error.
            raise NotificationError(f"Slack webhook failed: HTTP {response.status_code}")
