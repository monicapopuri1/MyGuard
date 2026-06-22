import logging
import os
import requests

log = logging.getLogger("whatsapp")


class WhatsAppSender:
    """
    Sends WhatsApp messages via Twilio or Meta WhatsApp Cloud API.
    Provider is selected by the WHATSAPP_PROVIDER env var ("twilio", "meta", or "mock").
    Use "mock" during local video testing — messages are printed to the log, not sent.
    """

    def __init__(self):
        self._provider = os.environ.get("WHATSAPP_PROVIDER", "twilio").lower()
        self._to = os.environ.get("GUARD_WHATSAPP_TO", "")

        if self._provider == "twilio":
            self._twilio_init()
        elif self._provider == "meta":
            self._meta_init()
        elif self._provider == "mock":
            log.warning("WhatsApp provider is MOCK — messages will be printed, not sent")
        else:
            raise ValueError(f"Unknown WHATSAPP_PROVIDER: {self._provider}")

        if not self._to:
            raise ValueError("GUARD_WHATSAPP_TO is not set")

        log.info("WhatsApp sender ready | provider=%s to=%s", self._provider, self._to)

    # ── Twilio ────────────────────────────────────────────────────────────────

    def _twilio_init(self):
        from twilio.rest import Client
        sid = os.environ["TWILIO_ACCOUNT_SID"]
        token = os.environ["TWILIO_AUTH_TOKEN"]
        self._twilio_client = Client(sid, token)
        self._twilio_from = os.environ["TWILIO_WHATSAPP_FROM"]

    def _send_twilio(self, body: str):
        msg = self._twilio_client.messages.create(
            body=body,
            from_=self._twilio_from,
            to=self._to,
        )
        log.info("Twilio message sent | sid=%s", msg.sid)

    # ── Meta WhatsApp Cloud API ───────────────────────────────────────────────

    def _meta_init(self):
        self._meta_phone_id = os.environ["META_PHONE_NUMBER_ID"]
        self._meta_token = os.environ["META_WHATSAPP_TOKEN"]
        self._meta_url = f"https://graph.facebook.com/v20.0/{self._meta_phone_id}/messages"

    def _send_meta(self, body: str):
        # Strip the "whatsapp:+" prefix that Twilio uses; Meta wants plain E.164
        to_number = self._to.replace("whatsapp:", "")
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": body},
        }
        headers = {
            "Authorization": f"Bearer {self._meta_token}",
            "Content-Type": "application/json",
        }
        resp = requests.post(self._meta_url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        log.info("Meta message sent | id=%s", resp.json().get("messages", [{}])[0].get("id"))

    # ── Public ────────────────────────────────────────────────────────────────

    def send(self, message: str):
        if self._provider == "twilio":
            self._send_twilio(message)
        elif self._provider == "meta":
            self._send_meta(message)
        else:
            log.info("[MOCK WHATSAPP] to=%s\n%s", self._to, message)
