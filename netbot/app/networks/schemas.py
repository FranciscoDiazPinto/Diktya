from pydantic import BaseModel, ConfigDict, Field


class NetworkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    site: str = Field(min_length=1, max_length=160)
    event_name: str = Field(min_length=1, max_length=160)
    external_id: str = Field(min_length=1, max_length=160)
    ssid: str = Field(min_length=1, max_length=64)
    vlan_tag: int | None = Field(default=None, ge=1, le=4094)


class NetworkRead(NetworkCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class NetworkSummary(BaseModel):
    """El cliente final no recibe identificadores de controlador ni VLAN."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    event_name: str
    ssid: str
