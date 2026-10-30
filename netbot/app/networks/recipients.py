"""Destinatarios de acceso Wi-Fi sin cuenta. La comparación no prueba posesión."""
import re
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from app.auth.models import User
from app.auth.access import require_user_permission
from app.auth.permissions import Permission
from app.core.errors import InvalidInput, NotFound
from .models import Network, NetworkRecipient
from .audit import record_audit


def normalize_contact(value: str) -> tuple[str, str]:
    value = value.strip()
    if '@' in value:
        from pydantic import TypeAdapter, ValidationError
        try:
            return 'email', str(TypeAdapter(EmailStr).validate_python(value)).casefold()
        except ValidationError:
            raise InvalidInput('Ingresa un correo válido o un teléfono con código de país.') from None
    if not re.fullmatch(r'(?:\+|00)[0-9 ()-]+', value):
        raise InvalidInput('Ingresa el teléfono completo con código de país, por ejemplo +56912345678.')
    digits = re.sub(r'[^0-9]', '', value)
    if value.startswith('00'):
        digits = digits[2:]
    if not re.fullmatch(r'[1-9][0-9]{7,14}', digits):
        raise InvalidInput('Ingresa un teléfono válido con código de país.')
    return 'phone', '+' + digits


class RecipientWrite(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, from_attributes=True)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)

    @model_validator(mode='after')
    def normalize(self):
        if not self.email and not self.phone:
            raise ValueError('Se requiere correo o teléfono.')
        try:
            if self.email:
                kind, self.email = normalize_contact(self.email)
                if kind != 'email':
                    raise ValueError('Correo inválido.')
            if self.phone:
                kind, self.phone = normalize_contact(self.phone)
                if kind != 'phone':
                    raise ValueError('Teléfono inválido.')
        except InvalidInput:
            raise ValueError('Correo o teléfono inválido. Usa código de país.') from None
        return self


class RecipientsWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    recipients: list[RecipientWrite] = Field(max_length=500)


def read_recipients(db: Session, actor: User, network_id: int) -> list[RecipientWrite]:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    if db.get(Network, network_id) is None:
        raise NotFound('Red no encontrada.')
    return [RecipientWrite.model_validate(row) for row in db.scalars(select(NetworkRecipient).where(NetworkRecipient.network_id == network_id).order_by(NetworkRecipient.id))]


def replace_recipients(db: Session, actor: User, network_id: int, payload: RecipientsWrite) -> list[RecipientWrite]:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    if db.get(Network, network_id) is None:
        raise NotFound('Red no encontrada.')
    db.execute(delete(NetworkRecipient).where(NetworkRecipient.network_id == network_id))
    db.add_all([NetworkRecipient(network_id=network_id, **row.model_dump()) for row in payload.recipients])
    record_audit(db, actor.id, network_id, 'wifi_recipients.updated')
    db.commit()
    return read_recipients(db, actor, network_id)


def matching_networks(db: Session, contact: tuple[str, str]) -> list[Network]:
    kind, value = contact
    condition = NetworkRecipient.email == value if kind == 'email' else NetworkRecipient.phone == value
    return list(db.scalars(select(Network).join(NetworkRecipient).where(condition).distinct().order_by(Network.id)))


def has_contact_data(message: str) -> bool:
    return bool(re.search(r'[^\s@]+@[^\s@]+|(?:\+|00)?[0-9][0-9 ()-]{7,}[0-9]', message))
