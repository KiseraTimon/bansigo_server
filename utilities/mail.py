# utilities/mail.py

"""
asynchronous mail sending

requires: aiosmtplib
"""

import logging
from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib

from config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Mail:
    """
    mail attributes
    """
    to: str
    subject: str
    body: str = ""
    html: str | None = None
    sender: str | None = None


class Mailer:
    """
    logic to process mailing-related events
    """

    # constructor
    def __init__(self, setting: Settings):
        """
        constructor
        :param setting: Settings
        """

        self.settings = setting

    def _build(self, mail: Mail) -> EmailMessage:
        """
        builds an email
        :param mail: Mail
        :return: EmailMessage
        """

        msg = EmailMessage()
        msg["Subject"] = mail.subject
        msg["From"] = mail.sender or self.settings.mail_default_sender
        msg["To"] = mail.to

        if mail.html and mail.body:
            """
            if both a body and html are provided for the mail
            """
            msg.set_content(mail.body)
            msg.add_alternative(mail.html, subtype="html")

        elif mail.html:
            """
            if only html is provided for the mail
            """
            msg.set_content(mail.html, subtype="html")

        else:
            """
            if only the body is provided for the mail
            """
            msg.set_content(mail.body)

        return msg


    async def send(self, mail: Mail) -> bool:
        """
        hands the mail to the SMTP server
        :param mail: Mail
        :return: bool
        """

        if not mail.to or not mail.subject:
            log.warning("Mail not sent: recipient and subject are required")
            return False

        s = self.settings
        try:
            msg = self._build(mail)

            if s.mail_suppress_send:
                log.info("MAIL_SUPPRESSED -> %s | %s\n%s", mail.to, mail.subject, mail.body)
                return True

            await aiosmtplib.send(
                msg,
                hostname=s.mail_server,
                port=s.mail_port,
                username=s.mail_username or None,
                password=s.mail_password.get_secret_value() if s.mail_password else None,
                use_tls=s.mail_use_ssl,
                start_tls=s.mail_use_tls,
                timeout=s.mail_timeout
            )

        except Exception:
            log.exception("Mail to %s failed (%s)", mail.to, mail.subject)
            return False


        log.info("Mail sent -> %s | %s", mail.to, mail.subject)
        return True
