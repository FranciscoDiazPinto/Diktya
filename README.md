# NetBot

Asistente para consultar y gestionar soporte de redes de eventos, con permisos por usuario y red.

## Estado implementado

- Autenticación y roles cliente, tecnico/operador, visor interno y admin.
- Conversaciones privadas persistentes; admin no obtiene acceso a chats ajenos.
- Monitoreo mediante OPNsense o datos mock, con dashboard y diagnóstico parcial por red.
- Entrega protegida de acceso Wi-Fi fuera del modelo y del historial.
- Tickets internos persistentes con confirmación, seguimiento y gestión por técnicos asignados.
- Reservas VLAN locales con confirmación. No aprovisionan VLANs ni SSIDs en la infraestructura.

Pendientes: integración UniFi, reinicio/adopción de APs, aprovisionamiento SSID/VLAN, trabajos durables, verificación/compensación, administración por chat, CSV y notificaciones externas. Una interfaz activa no prueba disponibilidad de Wi-Fi e Internet.

## Desarrollo y arquitectura

Leer [AGENTS.md](AGENTS.md) y la [guía modular vigente](netbot/docs/arquitectura-modular.md) antes de modificar código. Las instrucciones para IA en [CLAUDE.md](CLAUDE.md) apuntan a la misma guía compartida.

El proyecto ejecutable está en `netbot/`. Es un monolito modular Python/FastAPI y SQLAlchemy, con PostgreSQL para despliegue y SQLite para desarrollo/pruebas. El frontend actual es HTML/CSS y módulos ES, sin compilación ni React. OpenRouter se usa únicamente desde el backend. Docker Compose levanta PostgreSQL; API y frontend se arrancan por separado.

Consultar [inicio local, migraciones y pruebas](netbot/README.md), [índice de documentación](netbot/docs/README.md) y [soporte al cliente](netbot/docs/soporte-cliente.md).

El [documento de arquitectura original](Arquitectura/LEEME_PRIMERO_ARQUITECTURA.md) conserva el diseño objetivo y distingue sus partes pendientes del código actual.

## Integrantes del equipo y roles

| Integrante | Épicas a cargo | Rol / responsabilidad |
|---|---|---|
| **Francisco Díaz** | 001 · Autenticación y Roles<br>004 · Ejecución de Cambios | Seguridad base del sistema (login, roles y permisos) y lógica de ejecución de cambios sobre la infraestructura (VLAN, reinicio de dispositivos), incluyendo confirmación, verificación y rollback. |
| **Itamar Carrasco** | 002 · Monitoreo de Red<br>005 · Tickets y Notificaciones | Integración con las APIs de UniFi/OPNsense y dashboard de monitoreo; generación de tickets, clasificación de criticidad y notificaciones al equipo técnico. |
| **Bastián Herrera** | 003 · Chat, CSV y Reserva de VLAN<br>006 · Arquitectura Multi-Agente | Chat conversacional, carga masiva de SSIDs vía CSV y reserva de VLANs; diseño de la arquitectura de agentes en background que orquesta al resto de los módulos. |

Cada integrante es dueño de sus épicas de principio a fin (diseño, desarrollo e integración), en lugar de dividir el trabajo por capa técnica.

## Metodología de trabajo del equipo

El equipo trabaja bajo **Scrum**, con las siguientes prácticas:

- **Product Backlog** con épicas, historias de usuario y tareas priorizadas para el Producto Mínimo Viable (PMV).
- Desarrollo organizado en **sprints**, dentro de un cronograma total de **18 semanas**.
- **Revisión** de avances y pruebas de las funcionalidades desarrolladas al cierre de cada sprint.
- **Ajuste** continuo de la planificación y del Product Backlog según los resultados obtenidos.
- Distribución del trabajo por **épicas completas** (cada integrante lidera 2 épicas de extremo a extremo), en lugar de por capa técnica (frontend/backend/datos), favoreciendo la autonomía y la trazabilidad de cada bloque funcional.

## Organización técnica

Cada módulo posee sus datos y servicios. Los routers adaptan HTTP; los casos de uso autorizan, consultan y confirman operaciones; los adaptadores externos normalizan sus respuestas. El chat coordina servicios públicos y prepara propuestas con herramientas acotadas por permisos. La aplicación se compone en main/routes/lifecycle, sin dependencias inversas desde los dominios.

El frontend tiene controladores por funcionalidad y un compositor pequeño. Los cambios deben mantener sus límites y pasar las pruebas de arquitectura e aislamiento.
