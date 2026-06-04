"""Ponto de entrada de models do app `users`.

Os models vivem nos sub-módulos (auth/profiles/roles/otp) pra ficar tudo "MUITO bem separado"
(CONVENTION §2), mas o autodiscovery do Django importa só `users.models`. Reimportar aqui faz o
`makemigrations` enxergar todos sob o mesmo app_label `users` (um migration set só).
"""

from users.address.models import Address
from users.auth.models import User, UserManager
from users.auth.otp.models import OtpCode, OtpRateLimit
from users.documents.models import CNH, RG, Certificate, Document, Military
from users.profiles.models import Profile
from users.roles.lead.models import Checkout, Lead
from users.roles.models import UserRole

__all__ = [
    "User",
    "UserManager",
    "Profile",
    "UserRole",
    "OtpCode",
    "OtpRateLimit",
    "Address",
    "Document",
    "RG",
    "CNH",
    "Certificate",
    "Military",
    "Lead",
    "Checkout",
]
