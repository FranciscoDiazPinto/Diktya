# Arquitectura de NetBot

## Guía vigente para modificar el proyecto

Antes de implementar, leer [AGENTS.md](../AGENTS.md) y la [arquitectura modular vigente](../netbot/docs/arquitectura-modular.md). Esa guía describe contratos, dependencias, transacciones, arranque y pruebas del código actual.

El sistema implementado es un monolito modular FastAPI con PostgreSQL/SQLite y frontend estático en módulos ES. Los módulos auth, networks, tickets, chat, monitoring y changes tienen servicios propios; el chat usa APIs internas y no consulta tablas ajenas. FastAPI queda en adaptadores HTTP y los errores de aplicación se traducen en una frontera común.

El punto de entrada HTTP, el ciclo de vida, la preparación de la base y el registro de modelos están separados. Producción exige migraciones aplicadas antes del arranque; solo development/test admiten create_all. El frontend separa sesión/API, chat, monitoreo, soporte, tickets y reservas.

El flujo completo de cambios de infraestructura sigue pendiente. El directorio agents no contiene workers operativos; la tarea de muestreo actual corre en memoria. UniFi, React, WebSocket, ejecución durable, verificación/compensación y CSV son objetivos, no capacidades ya disponibles.

## Diseño de referencia histórico

Las secciones siguientes conservan la transcripción del diseño original. No deben usarse como inventario de funcionalidades terminadas ni como instrucciones que contradigan la guía vigente.

Este documento describe por escrito la arquitectura de software de **NetBot**. Su contenido se transcribió de los diagramas del *Documento 05 – Documento de Diseño* y de la *Guía Fase 2 – Desarrollo de Proyecto*. Se puede leer completo sin abrir ninguna imagen; las imágenes originales quedan en esta misma carpeta solo como respaldo (ver sección 11).

## Resumen

NetBot es un asistente que recibe solicitudes de cambio de configuración de red escritas en lenguaje natural (por web o por chat). Cada solicitud pasa por estas etapas:

1. Un **LLM** analiza la solicitud y genera un **plan de acción**.
2. El backend valida permisos y **reserva** el cambio.
3. El usuario **confirma** el cambio.
4. El backend **ejecuta** el cambio en **UniFi Controller** (Wi-Fi, VLANs, APs) y en **OPNsense** (firewall y VLANs).
5. El backend **verifica** el estado real de los dispositivos.
6. Todo se **registra en auditoría**.
7. Si la verificación falla, se hace **rollback**.

Patrón común de todos los flujos:

```
reserva → confirmación → ejecución → verificación → auditoría → (rollback si falla)
```

---

## 1. Stack tecnológico

| Capa | Tecnología | Responsabilidad |
|---|---|---|
| Frontend | **React** | Interfaz web y móvil; se comunica con el backend por API REST y WebSocket; gestión de sesiones |
| Backend | **Python + FastAPI** | Endpoints REST, coordinación de cambios, integración con el LLM y las APIs de red, gestión de configuración |
| Base de datos | **PostgreSQL** | Usuarios, configuraciones, historial de cambios y auditoría |
| IA | **LLM vía OpenRouter / Claude** (o cualquier proveedor compatible) | Interpretar solicitudes, generar planes de acción, clasificar incidentes por criticidad |
| Red | **UniFi Controller API** (HTTPS) | Gestión de red: SSIDs, VLANs, access points |
| Firewall | **OPNsense API** (HTTPS) | Reglas de firewall y VLANs |
| Infraestructura | **Docker** | Frontend, backend y base de datos corren como contenedores en un mismo Docker Host |

---

## 2. Vista lógica (capas)

La aplicación tiene tres capas internas y un grupo de servicios externos.

```
┌───────────────────────── Presentación ─────────────────────────┐
│ Frontend (React)                                               │
│  · Interfaz de usuario                                         │
│  · WebSocket / API REST                                        │
│  · Gestión de sesiones                                         │
└───────────────────────────────┬────────────────────────────────┘
                                │ HTTPS (JSON)
┌─────────────────────── Lógica de Negocio ──────────────────────┐   HTTPS (JSON)   ┌──── Servicios Externos ────┐
│ Backend (FastAPI)                                              │ ◄──────────────► │ LLM (OpenRouter / Claude)  │
│  · Endpoints REST                                              │                  │ UniFi Controller API       │
│  · Coordinación de cambios                                     │                  │ OPNsense API               │
│  · Integración con LLM y APIs                                  │                  └────────────────────────────┘
│  · Gestión de configuración                                    │
└───────────────────────────────┬────────────────────────────────┘
                                │ SQL (puerto 5432)
┌──────────────────────────── Datos ─────────────────────────────┐
│ PostgreSQL                                                     │
│  · Usuarios · Configuraciones · Historial de cambios · Auditoría│
└────────────────────────────────────────────────────────────────┘
```

Reglas que se desprenden de esta vista:
- La **presentación** solo habla con la **lógica de negocio**, nunca con la base de datos ni con los servicios externos.
- La **lógica de negocio** es la única capa que accede a PostgreSQL y a las APIs externas.

---

## 3. Diagrama de componentes

```
                HTTPS                HTTP/JSON                    API HTTPS
 ┌─────────┐ ─────────► ┌──────────┐ ─────────► ┌───────────────┐ ─────────► ┌───────────────────────┐
 │ Cliente │            │ Frontend │            │    Backend    │            │ LLM (OpenRouter/Claude)│
 │(navega- │ ◄───────── │ (React)  │ ◄───────── │   (FastAPI)   │ ◄───────── └───────────────────────┘
 │dor/móvil│            └──────────┘            └───┬───┬───┬───┘
 └─────────┘                                    SQL │   │   │ HTTPS
                                                    ▼   │   ▼
                                     ┌──────────────┐   │  ┌────────────────┐
                                     │ PostgreSQL   │   │  │ OPNsense (API) │
                                     └──────────────┘   ▼  └────────────────┘
                                                 ┌──────────────────────┐
                                                 │ UniFi Controller(API)│
                                                 └──────────────────────┘
```

| Origen | Destino | Protocolo |
|---|---|---|
| Cliente (navegador / móvil) | Frontend (React) | HTTPS |
| Frontend | Backend (FastAPI) | HTTP / JSON |
| Backend | LLM (OpenRouter / Claude) | API HTTPS |
| Backend | Base de datos (PostgreSQL) | SQL |
| Backend | UniFi Controller API | HTTPS |
| Backend | OPNsense API | HTTPS |

En el diagrama original, las conexiones del backend con la base de datos, UniFi y OPNsense aparecen con línea discontinua. Según la leyenda, eso marca una "conexión opcional" (ver sección 10).

---

## 4. Vista de despliegue

```
┌── Usuario ──────────┐                 ┌── Servidor de Aplicaciones (Docker Host) ─────────────────┐            ┌── Red / Dispositivos ──┐
│ Navegador web (React)│   Internet     │ ┌──────────┐  HTTP  ┌───────────┐  SQL  ┌────────────┐   │   HTTPS    │ UniFi Controller       │
│ Móvil (React)        │ ──(HTTPS)────► │ │ Frontend │ ─────► │  Backend  │ ────► │ PostgreSQL │   │ ─────────► │ (API HTTPS)            │
└──────────────────────┘                │ │ React    │        │  FastAPI  │       │            │   │            ├────────────────────────┤
                                        │ │ :80      │        │  :8000    │       │ :5432      │   │ ─────────► │ OPNsense (API HTTPS)   │
                                        │ └──────────┘        └───────────┘       └────────────┘   │            └────────────────────────┘
                                        └───────────────────────────────────────────────────────────┘
```

| Nodo | Contenido | Puerto |
|---|---|---|
| Dispositivo del usuario | Navegador web o app móvil (React) | — |
| Docker Host – contenedor Frontend | React | 80 |
| Docker Host – contenedor Backend | FastAPI | 8000 |
| Docker Host – contenedor BD | PostgreSQL | 5432 |
| Red / Dispositivos | UniFi Controller (API HTTPS), OPNsense (API HTTPS) | HTTPS |

- El usuario llega al frontend por **Internet (HTTPS)**.
- Dentro del Docker Host, el frontend se comunica con el backend por **HTTP** y el backend con la BD por **SQL**.
- Desde el Docker Host salen conexiones **HTTPS** hacia UniFi y OPNsense, en la red de dispositivos.
- El LLM es un servicio externo en Internet y el backend lo consume por HTTPS. No aparece en el diagrama de despliegue.

---

## 5. Casos de uso

**Actor principal:** Usuario (web / chat).
**Actores secundarios (sistemas externos):** Proveedor LLM (OpenRouter / Claude / compatible), UniFi Controller API (gestión de red) y OPNsense API (firewall).

Casos de uso del usuario:

| # | Caso de uso | Descripción |
|---|---|---|
| CU1 | Enviar solicitud de cambio de configuración | El usuario pide un cambio de red en lenguaje natural |
| CU2 | Consultar estado de un cambio | Ver en qué etapa está una solicitud o cambio |
| CU3 | Ver historial de cambios | Listar los cambios realizados |
| CU4 | Revisar logs / auditoría | Consultar el registro de auditoría |
| CU5 | Gestionar configuración (roles / credenciales) | Administrar roles de usuario y credenciales de servicios |

Casos de uso internos del sistema NetBot. CU1 los incluye con `«include»`:

| Caso interno | Sistema externo involucrado |
|---|---|
| Analizar solicitud con IA | Proveedor LLM |
| Generar plan de acción | Proveedor LLM |
| Ejecutar cambio en dispositivos / servicios | UniFi Controller API, OPNsense API |
| Verificar estado del cambio | UniFi Controller API, OPNsense API |
| Registrar en auditoría | — (base de datos propia) |

---

## 6. Modelo de datos (E-R propuesto)

> Según el propio diagrama, este es un "modelo lógico propuesto según requerimientos del README", así que todavía no es el esquema definitivo.

### Tablas

**`usuarios`**
| Campo | Tipo sugerido | Notas |
|---|---|---|
| id_usuario | int | **PK** |
| nombre | text | |
| email | text | |
| rol | text | |
| estado | text / bool | activo / inactivo |
| fecha_creacion | timestamp | |

**`solicitudes`**
| Campo | Tipo sugerido | Notas |
|---|---|---|
| id_solicitud | int | **PK** |
| id_usuario | int | **FK → usuarios** |
| tipo_cambio | text | ej. cambio de VLAN, carga de SSIDs |
| descripcion | text | texto original de la solicitud |
| estado | text | |
| fecha_solicitud | timestamp | |

**`cambios`**
| Campo | Tipo sugerido | Notas |
|---|---|---|
| id_cambio | int | **PK** |
| id_solicitud | int | **FK → solicitudes** |
| id_dispositivo | int | **FK → dispositivos** |
| accion | text | acción concreta a aplicar |
| estado | text | |
| fecha_ejecucion | timestamp | |
| resultado | text | |

**`dispositivos`**
| Campo | Tipo sugerido | Notas |
|---|---|---|
| id_dispositivo | int | **PK** |
| nombre | text | |
| tipo | text | AP, switch, firewall… |
| ip | text / inet | |
| descripcion | text | |
| estado | text | |

**`servicios`**
| Campo | Tipo sugerido | Notas |
|---|---|---|
| id_servicio | int | **PK** |
| nombre | text | |
| tipo | text | UniFi, OPNsense, LLM… |
| endpoint | text | URL de la API |
| credenciales | text | debe guardarse cifrado (ver sección 9) |

**`auditoria`**
| Campo | Tipo sugerido | Notas |
|---|---|---|
| id_auditoria | int | **PK** |
| id_solicitud | int | **FK → solicitudes** |
| id_usuario | int | **FK → usuarios** |
| accion | text | |
| detalle | text | |
| fecha | timestamp | |

### Relaciones

Las cardinalidades se transcribieron del diagrama tal como aparecen:

```
usuarios ──1───────1── solicitudes ──N───────1── dispositivos
                           │1                        │1
                           │                         │
                           │N                        │N
auditoria ──1───────N── cambios ──────N───────1── servicios
```

| Relación | Cardinalidad en el diagrama | Lectura |
|---|---|---|
| usuarios – solicitudes | 1 : 1 | En el diagrama de clases es 1 : 0..*. Lo correcto es **1 : N** (un usuario hace muchas solicitudes) |
| solicitudes – dispositivos | N : 1 | Muchas solicitudes pueden afectar a un mismo dispositivo |
| solicitudes – cambios | 1 : N | Una solicitud genera uno o varios cambios |
| dispositivos – servicios | 1 : N | Un dispositivo se gestiona mediante servicios (APIs) |
| cambios – servicios | N : 1 | Cada cambio se aplica a través de un servicio |
| auditoria – cambios | 1 : N | Los registros de auditoría se asocian a cambios |

---

## 7. Diagrama de clases

| Clase | Atributos | Métodos |
|---|---|---|
| `Usuario` | id: int, nombre: string, email: string, rol: string, estado: boolean | `enviarSolicitud()`, `verHistorial()` |
| `SolicitudCambio` | id: int, usuarioId: int, tipoCambio: string, descripcion: string, estado: string, fechaSolicitud: datetime | `analizarConIA()`, `generarPlanAccion()`, `validar()` |
| `Cambio` | id: int, solicitudId: int, dispositivoId: int, accion: string, estado: string, resultado: string, fechaEjecucion: datetime | `ejecutar()`, `verificar()`, `rollback()` |
| `Dispositivo` | id: int, nombre: string, tipo: string, ip: string, descripcion: string, estado: string | `aplicarConfiguracion()` |
| `Auditoria` | id: int, usuarioId: int, solicitudId: int, accion: string, detalle: string, fecha: datetime | `registrar()` |
| `ServicioExterno` | id: int, nombre: string, tipo: string, endpoint: string, credenciales: string | `conectar()`, `ejecutarAccion()` |
| `UniFiController` | id: int, ip: string, version: string | `aplicarConfig()`, `obtenerEstado()` |
| `OPNsenseFirewall` | id: int, ip: string, version: string | `aplicarRegla()`, `obtenerEstado()` |

### Asociaciones

| Desde | Hacia | Multiplicidad |
|---|---|---|
| Usuario | SolicitudCambio | 1 → 0..* |
| SolicitudCambio | Cambio | 1 → 0..* |
| Cambio | Dispositivo | 0..* → 1 |
| Dispositivo | Auditoria | 1 → (asociado) |
| Cambio | Auditoria | 0..* → 0..* |
| ServicioExterno | UniFiController | 1 → 1 |
| UniFiController | OPNsenseFirewall | 1 → 1 |

> Sugerencia para la implementación: `UniFiController` y `OPNsenseFirewall` pueden ser subclases (o adaptadores) de `ServicioExterno` con una interfaz común (`conectar`, `aplicar…`, `obtenerEstado`). Así un `Cambio` se ejecuta igual sobre cualquier proveedor y se pueden agregar otros sin tocar la lógica de negocio.

---

## 8. Flujos (diagramas de secuencia)

Notación: `A → B: mensaje` es una llamada y `A ⇠ B: mensaje` es una respuesta. Los bloques **alt** son alternativas excluyentes y **loop** es una repetición. La numeración es la de los diagramas originales.

### 8.1 Flujo general de un cambio de configuración

Participantes: Usuario (web/chat), Frontend (React), Backend (FastAPI), LLM (OpenRouter/Claude), UniFi Controller API, OPNsense API, BD (PostgreSQL).

1. Usuario → Frontend: envía la solicitud (cambio de configuración).
2. Frontend → Backend: envía la solicitud (API REST).
3. Backend → LLM: analiza y genera un plan (prompt + contexto).
4. LLM ⇠ Backend: respuesta (plan de acción).
5. Backend → UniFi: reserva el cambio (verifica el estado actual).
6. Backend → OPNsense: confirma y ejecuta el cambio.
7. OPNsense ⇠ Backend: resultado de la ejecución.
8. Backend → UniFi: verifica el estado (consulta las APIs).
9. UniFi ⇠ Backend: estado del cambio.
10. Backend → BD: registra en auditoría.
11. Backend ⇠ Frontend ⇠ Usuario: notifica el resultado (éxito o error, con detalles).

### 8.2 Cambio de VLAN solicitado por chat

Participantes: Usuario (Web), Frontend (React), Backend (FastAPI), LLM (OpenRouter/Claude), PostgreSQL, UniFi (API), OPNsense (API).

1. Usuario → Frontend: pide un cambio de VLAN en lenguaje natural.
2. Frontend → Backend: envía la solicitud.
3. Backend → LLM: analiza la solicitud y genera un plan.
4. LLM ⇠ Backend: respuesta (plan).
5. Backend: valida permisos y datos (proceso interno).
6. Backend → PostgreSQL: crea la reserva de cambio.
7. PostgreSQL ⇠ Backend: reserva creada.

**alt [Requiere confirmación]**

8. Frontend → Usuario: muestra la propuesta de cambio.
9. Usuario → Frontend: confirma el cambio.
10. Frontend → Backend: envía la confirmación (el backend la persiste en PostgreSQL).

**Ejecución**

11. Backend → UniFi: ejecuta el cambio de VLAN.
12. Backend → OPNsense: ejecuta el cambio de VLAN.
13. UniFi ⇠ Backend: resultado de UniFi.
14. OPNsense ⇠ Backend: resultado de OPNsense.
15. Backend → UniFi / OPNsense: verifica el estado.
16. UniFi / OPNsense ⇠ Backend: estado de la verificación.

**alt [Verificación correcta]**

17. Backend → PostgreSQL: registra el resultado OK.
18. Backend → PostgreSQL: registra la auditoría.
19. Backend ⇠ Frontend ⇠ Usuario: notifica el éxito.

**alt [Verificación fallida]**

17. Backend → UniFi: ejecuta el rollback.
18. Backend → OPNsense: ejecuta el rollback.
19. Backend → PostgreSQL: registra el rollback.
20. Backend → PostgreSQL: registra la auditoría.
21. Backend ⇠ Frontend ⇠ Usuario: notifica el error y el rollback.

**Puntos clave:** validar permisos antes de ejecutar; pedir confirmación explícita del usuario; verificar y hacer rollback si falla; registrar todo en auditoría.

### 8.3 Carga masiva de SSIDs vía CSV

Participantes: Usuario (Web), Frontend (React), Backend (FastAPI), PostgreSQL, UniFi (API), OPNsense (API).

1. Usuario → Frontend: sube el archivo CSV.
2. Frontend → Backend: envía el archivo.
3. Backend: valida el formato y el contenido.
4. Backend: obtiene el resultado de la validación.

**alt [Archivo inválido]**

5. Backend → Frontend: muestra los errores.
6. Frontend → Usuario: notifica el error.

**alt [Archivo válido]**

5. Backend → UniFi: reserva las VLANs necesarias.
6. UniFi ⇠ Backend: reserva creada.
7. Backend → Frontend: muestra la vista previa.
8. Frontend → Usuario: solicita confirmación.

**alt [Usuario confirma]**

9. Backend: aplica los SSIDs en lote.
10. Backend → UniFi: crea los SSIDs.
11. Backend → OPNsense: configura las VLANs.
12. UniFi ⇠ Backend: resultado de UniFi.
13. OPNsense ⇠ Backend: resultado de OPNsense.
14. Backend → UniFi / OPNsense: verifica los SSIDs.
15. UniFi / OPNsense ⇠ Backend: estado de la verificación.

**alt [Verificación correcta]**

16. Backend: genera el resumen.
17. Backend → Frontend: notifica el resultado.
18. Backend → PostgreSQL: registra en la BD.
19. Frontend → Usuario: notifica el resultado (en el original este paso aparece numerado como 13).

**alt [Verificación fallida]**

16. Backend → PostgreSQL: registra el error.
17. Backend ⇠ Frontend ⇠ Usuario: notifica el fallo.

**Puntos clave:** validar el CSV (formato y datos); reservar las VLANs antes de aplicar; mostrar vista previa y pedir confirmación; verificar y entregar un resumen final.

> El diagrama no especifica las columnas del CSV. Hay que definirlas (por ejemplo: `ssid`, `vlan_id`, `seguridad`, `contraseña`, `sitio`) antes de implementar.

### 8.4 Incidente, ticket y notificación

Participantes: Agente de Monitoreo (proceso en segundo plano), Backend (FastAPI), LLM (OpenRouter/Claude), Agente de Tickets (FastAPI), Equipo Técnico (receptor de notificaciones), PostgreSQL.

1. Agente de Monitoreo: detecta una anomalía (por ejemplo, la caída de un AP).
2. Agente de Monitoreo → Backend: envía la alerta.
3. Backend → LLM: analiza y clasifica la alerta.
4. LLM ⇠ Backend: resultado (criticidad).
5. Backend / LLM → Agente de Tickets: crea el ticket.
6. Agente de Tickets → PostgreSQL: registra el ticket.
7. PostgreSQL ⇠ Agente de Tickets: ticket creado.
8. Agente de Tickets → Equipo Técnico: notifica al equipo técnico.

**loop [Seguimiento periódico]**

10. Backend / LLM → Agente de Tickets: consulta el estado.
11. Agente de Tickets → PostgreSQL: actualiza el estado.
12. Agente de Tickets → Equipo Técnico: notifica la actualización.
13. Equipo Técnico ⇠ Backend / LLM: respuesta del equipo.

**alt [Incidente resuelto]**

14. Backend / LLM → Agente de Tickets: cierra el ticket.
15. Agente de Tickets → PostgreSQL: registra el cierre.
16. Agente de Tickets ⇠ Backend: notifica el cierre.

**alt [Requiere escalamiento]**

14. Backend / LLM → Equipo Técnico: escala el incidente.
15. Equipo Técnico → PostgreSQL: notifica y registra el escalamiento.

**Puntos clave:** detección automática por el agente de monitoreo; clasificación de criticidad con el LLM; creación y notificación del ticket; seguimiento periódico hasta la resolución.

> El diagrama original no incluye un paso 9; la numeración salta del 8 al 10.

---

## 9. Observaciones e inconsistencias detectadas

Conviene resolver estos puntos antes de implementar:

1. **Tickets e incidentes no están modelados.** Faltan la entidad o tabla `tickets` y los servicios *Agente de Monitoreo* y *Agente de Tickets* en las vistas de componentes, despliegue y clases.
2. **Reservas sin persistencia.** Los flujos usan "reserva de cambio" y "reserva de VLANs", pero el E-R no tiene una tabla ni un estado para las reservas. Se podría resolver con un valor `reservado` en `cambios.estado` o con una tabla `reservas`. Tampoco está claro dónde vive la reserva: según el flujo, en PostgreSQL o en UniFi.
3. **La cardinalidad usuarios–solicitudes no coincide.** En el E-R es 1:1 y en el diagrama de clases es 1:0..*. Lo correcto es **1:N**.
4. **Las credenciales se guardan en la BD** (`servicios.credenciales`). Deben ir cifradas o en un gestor de secretos o variables de entorno, nunca en texto plano.
5. **Algunas flechas apuntan al participante equivocado.** En el flujo de VLAN, "Crear reserva de cambio" apunta a UniFi y "Enviar confirmación" apunta a PostgreSQL. En este documento se interpretaron según su sentido lógico. En el flujo CSV y en el de incidentes, la numeración se repite o salta.
6. **No hay HTTPS en el contenedor del frontend.** El despliegue expone el frontend en el puerto 80. En producción hace falta TLS, por ejemplo con un reverse proxy como Nginx o Traefik delante.
7. **Falta definir la autenticación.** Existe "gestionar roles / credenciales", pero ningún diagrama dice cómo se autentica el usuario (JWT, sesiones, SSO) ni qué roles existen.
8. **El LLM no aparece en el despliegue.** Hay que contemplar su API key, la salida a Internet desde el backend, los límites de uso y qué hacer si el proveedor no responde.
9. **Formato del CSV sin definir** (ver sección 8.3).

---

## 10. Leyenda de los diagramas originales

| Elemento | Significado |
|---|---|
| Caja azul | Componente / contenedor |
| Caja morada | Servicio externo |
| Caja verde | Base de datos |
| Caja amarilla | Entidad / modelo |
| Flecha continua | Dependencia / flujo |
| Flecha discontinua | Conexión opcional (en los diagramas de secuencia, una respuesta) |
| Rectángulo discontinuo | Límite de contenedor |

Pie de la lámina general: *NetBot – Diagramas de Arquitectura y Diseño · Python + FastAPI | PostgreSQL | React | UniFi | OPNsense*.

---

## 11. Archivos de respaldo en esta carpeta

Este documento no depende de ellos, pero estas son las fuentes originales:

| Archivo | Contenido |
|---|---|
| `2_4_GuiaEstudiante_Fase_2_DesarrolloProyecto_APT_image3.png` | Lámina completa: casos de uso, vista lógica, E-R, clases, secuencia general, despliegue, componentes y leyenda |
| `Documento_05_-_Documento_de_Diseño_image3.png` | Secuencia: carga masiva de SSIDs vía CSV |
| `Documento_05_-_Documento_de_Diseño_image4.png` | Secuencia: cambio de VLAN solicitado por chat |
| `Documento_05_-_Documento_de_Diseño_image5.png` | Secuencia: incidente, ticket y notificación |
| `Documento_05_-_Documento_de_Diseño_image6.png` | Diagrama de componentes |
| `Documento_05_-_Documento_de_Diseño_image7.png` | Vista de despliegue |
| `Documento_05_-_Documento_de_Diseño_image8.png` | Diagrama de casos de uso |
| `Documento_05_-_Documento_de_Diseño_image9.png` | Modelo E-R propuesto |
| `Documento_05_-_Documento_de_Diseño_image10.png` | Diagrama de clases |
