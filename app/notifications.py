import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Message:
    user_id: str
    text: str


def format_inr(paise: int) -> str:
    """Integer paise to display text. Never goes through floats."""
    rupees, fraction = divmod(abs(paise), 100)
    sign = "-" if paise < 0 else ""
    return f"INR {sign}{rupees:,}.{fraction:02d}"


def build_messages(payload: dict) -> list[Message]:
    messages = []
    for entry in payload["entries"]:
        if entry["owner_id"] is None:  # system accounts are never notified
            continue
        verb = "credited to" if entry["direction"] == "credit" else "debited from"
        text = (
            f"{format_inr(entry['amount'])} {verb} account ending "
            f"{entry['account_id'][-4:]} ({payload['type']}). "
            f"Balance: {format_inr(entry['balance_after'])}."
        )
        messages.append(Message(user_id=entry["owner_id"], text=text))
    return messages


class LoggingNotifier:
    """Stand-in for an SMS/email provider. Swap this class for SES, Twilio, etc."""

    def send(self, message: Message) -> None:
        logger.info("NOTIFY user=%s text=%s", message.user_id, message.text)


notifier = LoggingNotifier()
