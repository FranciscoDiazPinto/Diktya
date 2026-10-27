"""Composición de metadata: único lugar autorizado a registrar modelos de todos los módulos."""
def register_models() -> None:
    from app.auth import models
    from app.changes import models as changes
    from app.chat import models as chat
    from app.networks import models as networks
    from app.networks import support_models
    from app.tickets import models as tickets
