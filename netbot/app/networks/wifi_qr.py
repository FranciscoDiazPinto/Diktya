"""QR generado localmente; nunca enviar el contenido a un servicio externo."""
import base64
import qrcode
from qrcode.image.svg import SvgPathImage
from .support_schemas import WifiCredential


def wifi_payload(credential: WifiCredential) -> str:
    def escape(value: str) -> str:
        return "".join(("\\" + c) if c in '\\;,:"' else c for c in value)
    security = {"open": "nopass", "wpa2-personal": "WPA", "wpa3-personal": "SAE"}[credential.security]
    password = credential.passphrase.get_secret_value() if credential.passphrase else ""
    return f"WIFI:T:{security};S:{escape(credential.ssid)};P:{escape(password)};;"


def wifi_qr_data_url(credential: WifiCredential) -> str:
    image = qrcode.make(wifi_payload(credential), image_factory=SvgPathImage, border=4)
    return "data:image/svg+xml;base64," + base64.b64encode(image.to_string()).decode("ascii")
