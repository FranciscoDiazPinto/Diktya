# NetBot

Agente inteligente para la gestión y monitoreo de infraestructura de red utilizada en eventos.

## Descripción

**Qué hace:** NetBot centraliza la administración de la infraestructura de red (puntos de acceso, VLANs, SSIDs) usada en eventos, actualmente gestionada de forma manual y dispositivo por dispositivo. Permite:

- Consultar el estado de la red mediante un **chat conversacional** en lenguaje natural.
- Visualizar un **dashboard de monitoreo** en tiempo real (APs, redes, alertas, disponibilidad, planos de cobertura).
- Ejecutar **cambios controlados** sobre la infraestructura (modificación de VLAN, carga masiva de SSIDs vía CSV, reinicio de dispositivos), siempre con confirmación explícita del usuario y con verificación y *rollback* posterior a la ejecución.
- Generar y hacer seguimiento de **tickets** ante incidentes, clasificando su criticidad y notificando al equipo técnico correspondiente.

**A quién va dirigido:** técnicos y administradores de red que gestionan infraestructura temporal (redes de evento), con al menos 3 roles distintos y restricciones sobre qué puede solicitar o ejecutar cada uno.

**Qué problema resuelve:** reduce el tiempo de respuesta y el riesgo de error humano asociado a la configuración manual de dispositivos de red durante un evento, aportando trazabilidad y control centralizado sobre cada cambio realizado.

## Tecnologías utilizadas

| Categoría | Tecnología |
|---|---|
| Backend | Python + FastAPI |
| Frontend | React (Vite) |
| Base de datos | PostgreSQL |
| Integraciones de red | API de UniFi Controller, API de OPNsense |
| Proveedor de LLM | OpenRouter, Claude u otro proveedor compatible, configurable vía API key |
| Despliegue | Red local, con proxy inverso / túnel para exponer el servicio de forma controlada |

> Nota: la selección de framework de frontend (React) es la recomendación actual del equipo; confirmar antes de iniciar el desarrollo si se mantiene o se ajusta.

## Instrucciones para ejecutar el proyecto localmente

### Requisitos previos

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- Acceso a un controlador UniFi y a un firewall OPNsense (o credenciales de prueba/sandbox)
- Una API key de un proveedor de LLM (OpenRouter, Claude, etc.)

### Backend

```bash
# Clonar el repositorio
git clone <url-del-repositorio>
cd netbot/backend

# Crear entorno virtual e instalar dependencias
python -m venv venv
source venv/bin/activate        # En Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Completar en .env:
#   DATABASE_URL=postgresql://usuario:password@localhost:5432/netbot
#   UNIFI_API_URL / UNIFI_API_KEY
#   OPNSENSE_API_URL / OPNSENSE_API_KEY
#   LLM_PROVIDER_API_KEY

# Ejecutar migraciones de base de datos
alembic upgrade head

# Levantar el servidor de desarrollo
uvicorn app.main:app --reload
```

El backend quedará disponible en `http://localhost:8000` (documentación interactiva en `http://localhost:8000/docs`).

### Frontend

```bash
cd netbot/frontend
npm install

# Configurar la URL del backend
cp .env.example .env
# VITE_API_URL=http://localhost:8000

npm run dev
```

El frontend quedará disponible en `http://localhost:5173`.

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

## Arquitectura de la solución

NetBot conecta directamente con la infraestructura de red del evento (UniFi y OPNsense), sin depender de sistemas externos intermedios. Los cambios sobre la red pasan siempre por un flujo de reserva → confirmación → ejecución → verificación, evitando que un dato quede duplicado o sobrescrito y permitiendo revertir la acción si la verificación posterior falla.

```mermaid
flowchart TD
    U["Usuario técnico"] -->|"Chat / Dashboard"| FE["Frontend (React)"]
    FE -->|"REST API"| BE["Backend (FastAPI)"]

    BE --> DB[("PostgreSQL")]
    BE --> LLM["Proveedor LLM\n(OpenRouter / Claude / otro)"]

    BE --> RES["Reserva de cambio\n(VLAN / SSID / reboot)"]
    RES --> CHK["Verificación de\ndoble escritura"]
    CHK -->|"Confirmado por el usuario"| EXE["Ejecución del cambio"]
    EXE --> UNIFI["API UniFi Controller"]
    EXE --> OPN["API OPNsense"]
    EXE --> VER["Verificación post-ejecución"]
    VER -->|"OK"| LOG["Registro / trazabilidad"]
    VER -->|"Falla"| RB["Rollback"]

    BE --> AGENTS["Agentes en background\n(monitoreo continuo, tickets)"]
    AGENTS --> UNIFI
    AGENTS --> OPN
    AGENTS -->|"Incidente detectado"| TICK["Generación de ticket\n+ notificación al equipo"]
```

**Componentes principales:**

- **Frontend (React):** chat conversacional y dashboard de monitoreo, consumido por los usuarios técnicos.
- **Backend (FastAPI):** expone la API REST, gestiona autenticación/roles, orquesta el flujo de cambios y coordina a los agentes en background.
- **Base de datos (PostgreSQL):** almacena usuarios, dispositivos, reservas de cambios, tickets y logs de auditoría.
- **Integraciones de red:** APIs de UniFi Controller y OPNsense, consumidas tanto para monitoreo como para ejecución de cambios.
- **Proveedor LLM:** interpreta las solicitudes del chat en lenguaje natural y las traduce en acciones propuestas sobre la infraestructura.
- **Agentes en background:** monitorean la red de forma continua, generan tickets ante incidentes y hacen seguimiento periódico hasta su resolución.
