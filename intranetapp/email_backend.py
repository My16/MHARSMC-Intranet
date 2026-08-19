"""
certifi_email_backend.py

A drop-in replacement for Django's SMTP EmailBackend that forces the TLS
handshake to use the `certifi` CA bundle instead of relying on the OS/Windows
trust store.

Why this exists:
Some Windows Server setups don't have Google's newer root/intermediate
certificates (e.g. "WE2, Google Trust Services") in their local trust store,
and Windows' Automatic Root Certificate Update feature isn't always enabled
or reachable on locked-down servers. `certifi` ships Mozilla's well-maintained
CA bundle, which already includes the needed roots, so pointing the SSL
context at it sidesteps the issue entirely -- no need to touch the Windows
certificate store or wait on IT/Windows Update.

Install location:
    Place this file inside your app package, e.g.:
        intranetapp/email_backend.py

Then in settings.py, set:
    EMAIL_BACKEND = 'intranetapp.email_backend.CertifiEmailBackend'

(If you keep the filename `certifi_email_backend.py`, adjust the dotted path
accordingly, e.g. 'intranetapp.certifi_email_backend.CertifiEmailBackend'.)
"""

import ssl
import certifi
from django.core.mail.backends.smtp import EmailBackend as DjangoSMTPBackend


class CertifiEmailBackend(DjangoSMTPBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Build an SSL context that trusts certifi's CA bundle instead of
        # whatever the OS/Windows trust store does (or doesn't) have.
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())