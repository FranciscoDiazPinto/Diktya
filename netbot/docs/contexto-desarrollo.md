# Contexto de desarrollo de Netbot

Notas internas consolidadas para mantener pocos archivos. Reutilizar este documento y las guias existentes antes de crear otro Markdown. La estructura final de entrega academica sigue pendiente; no se reorganizan las carpetas existentes.

- [Contexto y procedencia](#contexto)
- [Integraciones de red](#integraciones)
- [Decisiones y continuidad](#continuidad)
- [Gestion de SSID por chat](#ssid)
- [Matriz de evidencia](#evidencias)
- [Organizacion documental](#organizacion)


<a id="contexto"></a>

## Contexto y procedencia

Revisión documental y estática: 29 de octubre de 2026. Referencia consultada: repositorio independiente `diktya-atlas`, commit `6403ab0e1cb72141a3df6b51091a560f89254fd7` (13 de agosto de 2026). Base académica revisada: Netbot en `81c1dfe`, más la propuesta documental de gestión de SSID. No se ejecutó Atlas, no se instalaron sus dependencias ni se consultaron equipos o servicios reales.

### Propósito y separación de desarrollos

Netbot es el desarrollo académico para un caso real. `diktya-atlas` es otro desarrollo del autor para el cliente. Se conserva el conocimiento de interoperabilidad y las lecciones observadas para permitir una implementación propia en Python, sin portar, traducir o incorporar código, pruebas, migraciones, prompts, interfaz o documentos completos del otro producto.

No se trasladan direcciones, dominios operativos, IDs reales, inventarios del cliente, contactos, planos, respaldos ni credenciales. No se abren archivos `.env`, bases, volúmenes o carpetas externas de entrega para completar esta guía. Los nombres de endpoints y campos son referencias de interoperabilidad observadas en el snapshot; no certifican compatibilidad con una versión actual del fabricante.

El contexto documental del otro repositorio no impone reglas a este. La instrucción vigente del usuario es revisar y documentar; no conectar infraestructura ni implementar cambios en esta revisión. Las decisiones e instrucciones de Netbot prevalecen.

### Lectura sugerida

1. [Arquitectura vigente de Netbot](arquitectura-modular.md): qué existe en este repositorio.
2. [Contratos y particularidades de integración](contexto-desarrollo.md#integraciones): UniFi, OPNsense y fuentes intermediarias.
3. [Decisiones y continuidad](contexto-desarrollo.md#continuidad): alcance aceptado, riesgos de diseño y siguiente implementación.
4. [Matriz de evidencia](contexto-desarrollo.md#evidencias): archivos, símbolos y grado de certeza de cada hallazgo.
5. [Gestión de SSID por chat](contexto-desarrollo.md#ssid): comportamiento objetivo, todavía sin ejecutor real.

### Hallazgos que cambian las decisiones

| Asunto | Resultado de la revisión | Implicación para Netbot |
|---|---|---|
| Arquitectura de la referencia | TypeScript/Fastify, Prisma/PostgreSQL, Redis/BullMQ y React/Vite. | Mantener FastAPI/SQLAlchemy/Alembic y módulos ES. No migrar el stack para reutilizar la referencia. |
| UniFi | Hay cliente Integration API de UniFi OS, directo o por Site Manager Connector. | Ya se conoce una familia de API relevante y sus diferencias de transporte; falta fijar la versión/capacidades del entorno académico. |
| Tipo de controlador | Las notas históricas identifican un gateway EFG con UniFi OS. | No asumir un controlador clásico ni inventar la versión de UniFi Network. No demuestra qué equipo/versiones se usarán hoy. |
| Escritura de Wi-Fi | El cliente real solo reasocia una WLAN existente a una red/VLAN existente y ajusta bandas; rechaza creaciones. | Crear SSID y seleccionar AP para nuevos despliegues sigue siendo desarrollo nuevo. |
| OPNsense | El cliente directo de referencia consulta estado y gateways; sus escrituras siguen sin implementar. | No inferir que existe aprovisionamiento del firewall listo para reutilizar. Netbot ya posee su propio monitoreo OPNsense. |
| Nueva decisión del usuario | Elegir VLAN existentes, sin crear VLAN nuevas en OPNsense. | El siguiente bloque crea/modifica SSID y selecciona AP; no incorpora creación de VLAN, DHCP o reglas del firewall. |
| Arquitectura histórica de producción | Las notas más recientes de la referencia prescriben consumir una plataforma intermediaria llamada ATLAS; la migración del código es parcial. | Separar esa topología del cliente del diseño académico; no introducir esa dependencia ni modificar Netbot para cumplirla automáticamente. |
| Aprobación de cambios | Existen UI, reservas y workers, pero las herramientas del modelo pueden encadenar reserva y aplicación. | Mantener una confirmación humana comprobada por API, vinculada al actor y contenido exacto del plan. |
| Pruebas | El flujo de creación desde CSV usa un proveedor simulado que admite más operaciones que el cliente real. | Una prueba verde con mock no prueba creación de SSID en hardware. |
| Invitados | WhatsApp y vouchers se describen como diseño no implementado. | No confundirlos con el QR y recuperación por contacto que sí existen en Netbot. |

### Cómo interpretar estas guías

- **Código observado**: se siguió un símbolo y sus llamadores en el commit indicado. No implica que el camino se ejecute en el despliegue del cliente.
- **Prueba inspeccionada**: se leyó su cobertura y si usa mocks. No se ejecutó la suite de Atlas en esta revisión.
- **Validación histórica declarada**: las notas o comentarios dicen haber probado un caso real. No se reprodujo y no acredita el estado actual.
- **Decisión de Netbot**: procede de la conversación del usuario y del contrato vigente de este repositorio.
- **Recomendación**: requisito o criterio propuesto para una implementación independiente; no es funcionalidad terminada.

Las discrepancias entre README, comentarios antiguos, notas de arquitectura y código se conservan en la matriz. No elegir la afirmación más optimista como inventario funcional ni tratar una restricción escrita en un MD como un bloqueo técnico ya implementado.

### Estado del desarrollo académico

Netbot ya tiene autenticación y roles, asignaciones por red, chat privado persistente, monitoreo OPNsense/mock, tickets, reservas locales CSV y atención temporal sin cuenta con QR y recuperación por contactos administrables. La recuperación requiere la migración `006_network_recipients`; compara un correo o teléfono registrado, sin OTP. La sesión temporal no otorga un rol de usuario.

UniFi, creación/modificación real de SSID, selección aplicada de AP, trabajos durables y compensación siguen pendientes. Esta revisión actualiza documentación, no esas capacidades. No cambiar prompts para que anuncien escrituras antes de implementar y verificar el ejecutor.


<a id="integraciones"></a>

## Integraciones de red

Síntesis propia de la revisión identificada en [conocimiento técnico](contexto-desarrollo.md#contexto). La procedencia y los límites de cada observación están en [la matriz de evidencia](contexto-desarrollo.md#evidencias). No contiene configuración operativa del cliente ni código portado. Todo contrato de fabricante debe contrastarse con la documentación oficial y un laboratorio de la versión objetivo antes de programar escrituras.

### 1. Separar los identificadores

Un sitio de UniFi, una red de UniFi, un Wi-Fi Broadcast, un AP y una VLAN de OPNsense son recursos distintos. El nombre visible del SSID no identifica por sí solo una red ni una WLAN entre sitios. El tag VLAN tampoco identifica por sí solo una interfaz o red entre proveedores.

En UniFi OS el sitio tiene UUID y referencia interna; el cliente de referencia resuelve esa referencia antes de consultar recursos. La red de UniFi tiene su propio ID y etiqueta VLAN. El broadcast referencia la red por ID; el AP se referencia por ID del dispositivo. En Netbot la VLAN OPNsense se identifica actualmente por interfaz padre y tag.

Para un plan propio se requiere una correspondencia explícita: ámbito académico/sitio/evento, sitio del controlador, red UniFi y su VLAN, interfaz padre/tag OPNsense y conjunto de AP. Conservar IDs estables y nombres como etiquetas de presentación. No derivar permisos de un nombre ni asumir que el mismo número en dos sitios representa el mismo recurso. La referencia contiene métodos cuyo argumento de sitio se usa como etiqueta mientras la consulta utiliza el sitio configurado: no reutilizar ese comportamiento como solución multi-sitio.

### 2. Familias de API UniFi

#### Integration API de UniFi OS

La referencia usa autenticación por API key en un encabezado, separada de la sesión clásica por cookie. El camino directo observado tiene prefijo `/proxy/network/integration/v1`. Los sufijos siguientes son relativos a ese prefijo; describen lo visto en el código, no una garantía universal:

| Método y recurso | Uso observado |
|---|---|
| `GET /sites` | Descubrir el sitio y resolver la referencia interna a UUID. |
| `GET /sites/{siteId}/devices` | Inventario de equipos adoptados. |
| `GET /sites/{siteId}/clients` | Clientes y referencia al dispositivo de enlace. |
| `GET /sites/{siteId}/devices/{deviceId}/statistics/latest` | Uptime/heartbeat cuando están disponibles. |
| `GET /sites/{siteId}/networks` | Redes, IDs y etiquetas VLAN. |
| `GET /sites/{siteId}/wifi/broadcasts` | WLAN/SSID y referencias de red/difusión. |
| `GET /sites/{siteId}/wifi/broadcasts/{broadcastId}` | Configuración detallada de un broadcast. |
| `PUT /sites/{siteId}/wifi/broadcasts/{broadcastId}` | Modificar un broadcast existente. |
| `POST /sites/{siteId}/devices/{deviceId}/actions` | Acción de reinicio; no implica que el equipo se recuperó. |
| `GET /pending-devices` | Pendientes de adopción; no están aún dentro del recurso de un sitio. |
| `POST /sites/{siteId}/devices` | Adopción por MAC en el cliente de referencia; no validada físicamente en esta revisión. |

La referencia **no implementa POST para crear broadcast ni crear Network**. Que un fabricante exponga esas operaciones en alguna versión no implica que el desarrollo revisado las implemente. El diseño nuevo de Netbot debe comprobar la superficie de creación, requisitos de seguridad y capacidad de seleccionar AP en el entorno objetivo.

#### Acceso directo y Site Manager Connector

El cliente directo construye rutas bajo el host de la consola y el prefijo anterior. El transporte cloud observado usa la base pública de Site Manager `https://api.ui.com/v1/connector/consoles/{consoleId}` y el sufijo `/network/integration/v1/...`: el conector ya incorpora el proxy y duplicarlo produce rutas incorrectas.

La API key de la consola, la API key de Site Manager y las credenciales de otros productos UniFi son configuraciones de distinto ámbito. No son intercambiables ni se seleccionan automáticamente tras un error. El conector cloud requiere WAN; no cumple por sí solo una operación local sin Internet. Separar transporte, autenticación y modelo de dominio al diseñar un adaptador propio; no copiar el cliente TypeScript.

#### API clásica y otros productos

La referencia conserva un camino clásico de login/cookie para alarmas, con rutas `/api/s/{site}/...`; sus notas advierten que no fue validado contra la misma consola UniFi OS. Un 404 no se arregla automáticamente creando una cuenta ni usando otra key: puede ser ruta, transporte o versión incorrecta. No introducir un fallback automático de autenticación o escrituras a la API clásica.

UniFi Mobility es otro producto y cliente de la referencia, con dispositivos/workspaces y credenciales propios. No sirve como reemplazo de las operaciones Network AP/SSID/VLAN. La API intermediaria ATLAS tampoco es la Integration API del fabricante.

### 3. Formas de respuesta y errores que deben probarse

Los listados observados usan un envoltorio con `data` y metadatos de paginación. Recursos individuales como detalle de broadcast, estadísticas y respuesta PUT se consumen como objetos directos. No aplicar el mismo desempaquetado a todos los endpoints. Las acciones pueden responder sin cuerpo: no intentar parsear JSON de manera incondicional.

La implementación de referencia recorre listados de dispositivos/clientes/redes/broadcasts con `offset`, `limit` y `totalCount`; pide páginas de 200 y corta con página vacía o total alcanzado. Eso es una observación de su contrato, no un límite fijo para toda versión. El listado de sitios no pasa por el mismo paginador. Netbot debe verificar la paginación de **todos** los listados, limitar páginas/elementos y detectar respuestas incoherentes para no ciclar ni truncar silenciosamente.

Probar por separado errores de autenticación, permiso, ruta no disponible, límite de frecuencia, servidor, timeout, TLS, JSON inválido y contenido no conforme. Mantener los errores tipados del cliente Python existente. No seguir redirecciones hacia hosts arbitrarios ni volcar cabeceras/cuerpos con secretos en logs.

### 4. SSID, VLAN, bandas y AP

El overview de un broadcast puede omitir `network` cuando utiliza la red nativa. La referencia acepta tanto ausencia como `NATIVE` y resuelve la VLAN desde la Network por defecto; `SPECIFIC` lleva un `networkId`. Para Netbot, una referencia específica que no aparece en el inventario debe producir estado no resoluble/conflicto, **no** asignarse silenciosamente a la red por defecto. No asumir que la VLAN nativa siempre es 1.

Las frecuencias observadas son valores numéricos como 2.4, 5 y 6, distintos de las etiquetas de presentación. Preservar bandas desconocidas como no soportadas en vez de convertir cualquier número distinto de 2.4/5 a 6. Algunos tipos de broadcast no incluyen la lista de frecuencias.

El filtro de difusión observado distingue:

- Sin filtro o filtro nulo: todos los equipos capaces de actuar como AP.
- `DEVICES`: lista explícita de IDs de dispositivo.
- `DEVICE_TAGS`: requiere resolver tags/grupos. La referencia no lo resuelve y no puede dar una lista completa de AP en ese caso.

Un conjunto de AP no resuelto no equivale a difusión vacía ni autoriza a difundir en todos. Netbot debe mostrar selección explícita, rechazar recursos fuera de ámbito y verificar el conjunto exacto tras ejecutar. No ampliar automáticamente un plan que no especifica AP. Asociar un AP a un punto de un plano tampoco configura difusión en el controlador.

### 5. Escrituras y conservación de seguridad

La reasignación real observada busca un broadcast y una Network existentes, lee el detalle completo y realiza un PUT conservando la configuración de seguridad y el resto de atributos, cambiando solo referencia de red y bandas. En ese contrato PUT no se trata como PATCH.

Lecciones para una implementación independiente:

- Preparar el cambio a partir del esquema soportado de la versión objetivo. Confirmar qué campos son de solo lectura y qué devuelve el controlador censurado; no reenviar indiscriminadamente todo un JSON ni sustituir una clave por una máscara.
- No convertir un SSID protegido en abierto para suplir datos faltantes. Para nuevas WLAN definir perfil de seguridad y referencia a secretos mediante formulario protegido.
- No enviar detalle completo de seguridad al LLM, al historial o a la auditoría. El adaptador usa secretos en el servidor; el resto recibe DTO mínimos.
- Distinguir éxito de escritura, configuración releída, despliegue a AP y prueba de conectividad. Son evidencias diferentes.
- Reconciliar un timeout de escritura antes de repetirlo; no crear duplicados ni deshacer un cambio de otro actor.

El worker de referencia relee VLAN/bandas y ensaya restaurar la configuración anterior. Su comprobación no cubre la selección de AP, toda la seguridad ni el camino de conectividad; para nuevas creaciones tampoco tiene un estado anterior al cual volver. Netbot necesita su propia definición de verificación y compensación por operación.

### 6. Inventario y telemetría

La referencia combina equipos, clientes por `uplinkDeviceId`, broadcasts y estadísticas por equipo. Una consulta de estadísticas fallida no invalida todo el inventario. Hay un costo N+1 que debe limitarse y cachearse según antigüedad tolerable.

No todos los equipos exponen features suficientes para clasificar su tipo; las notas señalan excepciones de gateways y UPS. Clasificación incierta debe quedar desconocida, sin habilitar acciones peligrosas por inferencia del modelo. No todos los endpoints exponen señal/RSSI. La ausencia no se representa como 0 dBm.

No usar la hora de consulta como si fuera el último heartbeat del equipo. Conservar `checked_at`, observación remota, fuente, antigüedad, incidencias y si los datos son simulados. Si un proveedor no expone clientes por AP o sus SSID, entregar desconocido/no soportado en vez de cero/lista vacía con apariencia de dato medido.

### 7. OPNsense

La autenticación directa observada usa HTTP Basic con API key y API secret; no usa la API key ni el login de UniFi. Los métodos directos del snapshot consultan:

- `/api/diagnostics/system/systeminformation` para información del sistema.
- `/api/routes/gateway/status` para estados de gateways y alertas derivadas.

Netbot usa su propio adaptador y una variante `/api/diagnostics/system/system_information`, además de recursos, interfaces, VLAN, DHCP y firewall. La diferencia de nombres se registra como compatibilidad a verificar, no como autorización para reemplazar rutas sin probar la versión. Conservar la recolección parcial y clasificación 401/403/404/timeout/TLS existente en Python. El cliente directo de la referencia no configura timeout en su petición OPNsense: no trasladar esa omisión.

La lógica de gateways de referencia trata `none` como saludable y ciertos valores de caída como críticos; las notas dicen haber observado en vivo el caso sano, no todos los degradados. Un estado no reconocido no se debe interpretar como sano ni una indisponibilidad de la API como caída física confirmada.

El cliente OPNsense de referencia reutiliza una interfaz orientada a WLAN y deja escrituras sin implementar. Netbot debe mantener contratos específicos: monitoreo, inventario VLAN y aprovisionamiento Wi-Fi no son una sola interfaz. El alcance confirmado es **usar VLAN existentes**. No agregar endpoints de creación de VLAN, DHCP, NAT o firewall en este bloque.

Una pareja HA no se certifica consultando solo un miembro, ni una segunda URL acredita redundancia si termina en el mismo backend. Sincronización CARP/configuración, transporte de administración y operación de una app son planos distintos. No inventar instrucciones de dual-write ni de recuperación para la infraestructura del cliente.

### 8. Plataforma intermediaria de referencia

Las notas de agosto describen una plataforma distinta llamada ATLAS y el repositorio de aplicación renombrado conceptualmente a ARGOS. No confundir esos nombres con Netbot académico. El código monitoriza inventario y estado de los firewalls por el cliente intermediario; otros caminos aún usan UniFi directamente. La prescripción documental de no consultar equipos directamente no está aplicada uniformemente en el snapshot.

El cliente intermediario agrupa salud/versiones, estado de componentes, inventario, eventos/alertas/historial, telemetría/RF, energía, clientes, tráfico y búsqueda. No hay escritura de infraestructura en ese cliente. No se dispone aquí del contrato externo completo referido por sus notas y no se buscó fuera del repositorio.

Lecciones generales, sin adoptar ese servicio como dependencia:

- Validar semántica del cuerpo: HTTP 200 con `ok:false` no es dato sano.
- Separar degradación parcial de ausencia completa. No perder los fallos por componente.
- Asignar timeouts según operación: la referencia distingue consultas rápidas de energía o virtualización lentas. Son presupuestos históricos, no SLO universales.
- No usar nombres renombrables como IDs de equipos. El intermediario revisado no aporta una identidad inmutable completa y el normalizador documenta duplicados tras renombrar.
- No usar un recuento agregado como prueba de coherencia HA; validar el indicador/contrato correspondiente y las versiones históricas de los detalles.
- Preservar cero, falso, ausencia y vacío como valores diferentes. Un default por verdad/falsedad puede ocultar el peor estado.
- Una respuesta truncada sin cursor de eventos no representa necesariamente toda la ventana histórica; mostrar los límites y la cobertura temporal.
- No importar el HTTP sin autenticación de ese segmento privado como política para el sistema académico.

La decisión de proveedor para Netbot debe quedar en un ADR propio, con seguridad, capacidades y laboratorio definidos. Esta revisión no conecta ni incorpora la API intermediaria del cliente.


<a id="continuidad"></a>

## Decisiones y continuidad

Decisiones y recomendaciones para implementar con diseño propio. Contexto y procedencia: [síntesis de la revisión](contexto-desarrollo.md#contexto), [contratos observados](contexto-desarrollo.md#integraciones) y [matriz de evidencia](contexto-desarrollo.md#evidencias). Este documento no habilita operaciones sobre infraestructura real.

### Decisiones ya tomadas para Netbot

Confirmación adicional del usuario el 29 de octubre de 2026: se utilizará la API oficial de UniFi con una API key generada desde su portal. Administrador y técnico deben poder **crear SSID nuevos tanto por carga CSV como por chat**, elegir AP específicos y asociar VLAN existentes. No limitar el alcance a modificar WLAN ya creadas por las limitaciones del cliente Atlas revisado. El formulario/lote y el chat deben compartir las mismas validaciones, confirmación y ejecución.

«Portal de UniFi» identifica dónde se administra/genera la clave, pero aún no fija si su ámbito es la consola Network local o Site Manager ni cuál es la URL de conexión. Confirmar ese ámbito y la versión/documentación del controlador antes de seleccionar transporte. No usar ni pedir la clave en conversación o Markdown.

1. Conservar el monolito modular Python/FastAPI, SQLAlchemy/Alembic y frontend ES. No migrar a TypeScript, React, Prisma o BullMQ para reproducir el producto de referencia.
2. Técnico/operador y administrador deben poder solicitar creación/modificación de SSID, elegir AP explícitos y asociar una **VLAN existente**. Crear VLAN nuevas, DHCP, NAT y reglas OPNsense queda fuera de este bloque.
3. Permisos más asignaciones por recurso, no solo rol. Hace falta definir ámbito de aprovisionamiento para nuevas redes, además de las asignaciones a redes ya existentes.
4. Chat consulta/prepara; API confirma el plan exacto; ejecutor durable aplica y verifica. Una herramienta del LLM no confirma ni encola por su cuenta una operación aprobada supuestamente «en la conversación».
5. Carga CSV y cambios posteriores deben compartir el mismo motor de planes, conservando la distinción entre reservas locales y despliegues. No alterar automáticamente el contrato CSV actual para adoptar las columnas del otro desarrollo.
6. Invitado mantiene sesión temporal sin cuenta y recuperación por correo o teléfono registrado, fuera del LLM. No recibe inventario técnico ni permiso de cambio por conocer el contacto. La comparación no es OTP, voucher ni credencial única de red.
7. La revisión de Atlas se limita a conocimiento y MD. No se conectan servicios reales, no se modifica el repositorio del cliente y no se incorporan dependencias hacia él.

### Qué ya está y qué debe construirse

| Área | Implementado en Netbot | Trabajo siguiente |
|---|---|---|
| Identidad y ámbitos | Roles, usuario activo, asignaciones por red y chat privado con historial del servidor. | Ámbito explícito sitio/evento/AP/VLAN para crear nuevas redes y reautorizar trabajos pendientes. |
| UniFi | Sin adaptador operativo. | Contrato Python propio de inventario y aprovisionamiento, implementación de laboratorio y matriz de capacidades por versión. |
| OPNsense | Monitoreo e inventario VLAN con proveedor mock/real, errores tipados y datos parciales. | Correspondencia autorizada con Networks UniFi existentes; no crear VLAN ni reemplazar el cliente por el stub de referencia. |
| CSV | Validación, vistas previas privadas, confirmación y reservas locales, migración 005. | Preparar despliegues sobre filas/reservas elegidas, con seguridad/AP explícitos y resultados por operación. |
| Plan individual | Diseño en `contexto-desarrollo.md#ssid`. | Propuesta tipada, baseline completo, versión, vencimiento y confirmación vinculada al actor. |
| Trabajos | Sin ejecutor durable de aprovisionamiento. | Persistencia, idempotencia, control de concurrencia, recuperación tras reinicio y conciliación. |
| Wi-Fi de clientes | Referencias a secretos, acceso protegido, QR, registro de destinatarios y atención temporal; migración 006. | Conectar el resultado del futuro despliegue al inventario y referencia del secreto sin revelar claves al modelo. |
| Historial de disponibilidad | Métricas/cache/historial de tráfico del monitoreo vigente. | Si se agrega disponibilidad persistente, diferenciar periodos sin observación y falta de muestreo de caída confirmada. |

### ADR que falta antes del adaptador real

Registrar en un documento de decisión propio:

- Versión exacta de UniFi Network, tipo de consola y capacidades de su API para crear WLAN y seleccionar AP. El snapshot aclara que la referencia usó UniFi OS/EFG; no fija la versión del laboratorio o despliegue académico.
- API oficial UniFi con API key del portal, según confirmación del usuario. Precisar si corresponde a Network local o Site Manager y su URL base; no asumir una API intermediaria ATLAS ni trasladar las reglas de topología del cliente a Netbot.
- Autenticación con permisos mínimos, CA/TLS y transporte. Los secretos se suministran por un canal de entorno protegido; no se piden ni se guardan en MD.
- Identidad estable de sitios/AP/redes y correspondencia VLAN OPNsense↔Network UniFi. Cómo se asignan esos recursos a técnico/evento sin otorgar todo un sitio implícitamente.
- Perfil de seguridad soportado para nuevas WLAN y gestión del secreto en el servidor. No degradar a red abierta por faltar configuración.
- Evidencia necesaria para afirmar «configurado», «difundido por AP» y «conectividad verificada». Definir qué no puede observar el proveedor.

Registrar «no soportado/no disponible» cuando falte un contrato, no inventar endpoints. Validar con documentación oficial de la versión y respuestas de laboratorio anonimizadas; no reutilizar fixtures ni capturas privadas de Atlas.

### Ejecución propia: requisitos de aceptación

#### Plan y confirmación

El servidor prepara una representación inmutable o versionada de la operación, actor, ámbito, origen CSV opcional, recursos afectados, estado remoto previo y propuesta. La interfaz muestra diferencias y AP concretos. Cambiar SSID, red/VLAN, AP, seguridad o baseline invalida la aprobación anterior.

El backend verifica permiso y propiedad/ámbito al emitir el plan, confirmar y ejecutar, también después de esperas externas. No aceptar identidad/rol/historial del navegador o modelo como autorización. Invitados, clientes y visores reciben denegación aunque invoquen directamente la API.

#### Persistencia y concurrencia

El registro durable debe permitir distinguir preparado, confirmado, pendiente, ejecutando, completado, fallido y resultado incierto/pendiente de conciliación. No prometer una transacción atómica entre la base y los equipos. Vincular la confirmación a un ID de trabajo/idempotencia único para evitar duplicados cuando se reintenta una solicitud.

Serializar según todos los recursos que entren en conflicto: una exclusión por VLAN destino no protege dos operaciones concurrentes sobre el mismo SSID. Comprobar versión/baseline de los atributos relevantes, no solo tag VLAN. Al introducir múltiples sitios, diseñar claves e índices con sitio/identidad de recurso; no copiar una unicidad por todos los estados que impida conservar varias operaciones históricas.

Los límites de lock, reintentos y tiempo se dimensionan por operación. Perder el lock o recibir timeout tras enviar una escritura no permite repetir o revertir a ciegas. Conciliar el estado remoto y dejar trazabilidad. No convertir el muestreo en memoria de FastAPI en una cola «durable» por cambiarle el nombre.

#### Verificación y compensación

Releer los atributos afectados y verificar AP exactos, red/VLAN y seguridad soportada. Distinguir convergencia tardía de fallo definitivo con una espera acotada. La respuesta inmediata del PUT no es la única evidencia.

Si se modifica un recurso existente, conservar los datos necesarios para restaurarlo sin secretos en logs ni sobrescribir cambios ajenos. Si se crea uno nuevo, compensar únicamente lo creado por ese trabajo y cuando se pueda demostrar su propiedad/uso; no eliminar recursos preexistentes o compartidos. Resultado parcial o incierto debe producir un estado visible y una incidencia, no un éxito genérico.

### Pruebas que deben preceder a hardware real

- Contratos con listado/detalle/acción, paginación completa, nulos/ausentes, VLAN nativa y específica, filtros AP/tags y respuestas semánticamente fallidas.
- Configuración: booleans explícitos, HTTPS/CA, transporte directo/conector y credenciales de ámbito incorrecto. Conservar timeout y clasificación de errores del cliente Python.
- Accesos cruzados entre clientes/técnicos/sitios, modificación de IDs, revocación tras confirmación y después de esperas externas.
- El modelo intenta reservar/aplicar sin confirmación; la API y el ejecutor lo impiden. No simular la aprobación llamando directamente al worker y contar eso como prueba del gate humano.
- Cambios simultáneos al mismo SSID y VLAN; confirmaciones duplicadas; reinicio entre escritura y persistencia; timeout de resultado incierto; compensación fallida.
- Mock fiel a capacidades: si el proveedor real no crea WLAN, el mock no debe convertir esa ausencia en un caso de éxito operacional. Separar pruebas de dominio, contrato HTTP y laboratorio.
- Secretos ausentes del prompt, resultados, auditoría, historial y almacenamiento del navegador; seguridad existente preservada y ninguna conversión implícita a abierto.
- Cambios individuales después del CSV conservan filas y configuraciones ajenas. Los resultados del lote explican lo parcial.

Los servicios y credenciales de prueba deben estar aislados de producción. El setup de la referencia documenta una contaminación histórica de la base real antes de introducir un cambio de nombre de base e índice Redis. No ejecutar suites externas ni asumir que cambiar un sufijo convierte el host/credencial del cliente en un laboratorio seguro. En Netbot conservar las fixtures aisladas actuales y añadir infraestructura de pruebas propia cuando se incorporen colas/adaptadores.

### Lecciones operativas que conviene conservar sin copiar el producto

**Operación sin WAN.** Las funciones locales de consulta/recuperación no deberían caerse porque OpenRouter o un canal de notificación no responde. Preparar degradación explícita, datos con antigüedad visible y artefactos disponibles localmente. El conector cloud y el LLM externo son dependencias WAN distintas. No habilitar escrituras con inventario vencido por estar offline.

**Notificaciones.** Separar auditoría persistida de entrega externa. Un email stub, canal sin configurar o fallo parcial no significa «notificado». Si se implementan canales, registrar entrega/reintento y limitar datos al destinatario autorizado. Los detalles históricos de precios/proveedores de mensajería deben revisarse de nuevo antes de usarse; esta extracción no los adopta.

**Disponibilidad.** Una foto actual no prueba todo un periodo. Mantener línea de tiempo, cobertura de observación y estado desconocido. No rellenar silencios ilimitados como online por el último evento ni contar todo el tiempo previo al primer registro como offline.

**Planos.** Recinto, evento y zona tienen identidades y escalas independientes. Colocar un AP en un plano es planificación, no adopción ni configuración UniFi. Una estimación geométrica debe etiquetarse como estimación, sin presentarla como señal RF medida.

**Auto-remediación.** Queda fuera del bloque SSID solicitado. Si se diseña después, requerirá política explícita, equipos autorizados, límites, cooldown desde el intento y distinción entre recuperación espontánea y efecto del comando. No habilitar reinicios o readopción automática al incorporar un adaptador.

**Sesiones y tiempo real.** Mantener la renovación compartida y aislamiento de sesión existentes. No adoptar el historial cliente del otro producto. Si se agrega WebSocket, autenticar, filtrar por ámbito y revocar suscripciones; Redis pub/sub y botones ocultos no sustituyen autorización. Una migración futura a cookies requiere diseño propio de CSRF/CORS, no copiar solo una parte del flujo.

**Despliegue.** Respaldar base y archivos persistidos, y ensayar restauración en un entorno aislado. Un script/volumen existente no prueba recuperación. No ejecutar los scripts de despliegue de la referencia ni heredar sus hosts, DNS, overlays, identidades o reglas de rescate.

### Orden de continuación

1. Resolver el ADR de proveedor/laboratorio y capacidades por versión. La elección de VLAN **ya está resuelta**: existentes.
2. Diseñar autorización por ámbito y DTO mínimos de inventario. Agregar migraciones nuevas solo cuando se implemente el contrato.
3. Implementar plan/propuesta y su confirmación HTTP, compartidos por chat y filas CSV.
4. Implementar trabajos persistentes e idempotencia, primero con simulación etiquetada y pruebas de fallos.
5. Implementar adaptador propio de la API acordada y pruebas de contrato de laboratorio.
6. Conectar la selección AP/VLAN/seguridad en la interfaz y herramientas de consulta/propuesta; actualizar la política de chat al existir la capacidad.
7. Validar creación, modificación y compensación en laboratorio; después evaluar el despliegue real por su proceso separado.

No cambiar el estado «pendiente» de estas operaciones a «implementado» por completar solamente documentación, mocks, una herramienta de propuesta o una prueba de lectura.


<a id="ssid"></a>

## Gestion de SSID por chat

Estado: alcance solicitado y diseño de implementación; todavía no implementado. Fecha: 29 de octubre de 2026. Esta guía no convierte las reservas CSV actuales en despliegues reales.

Actualización tras revisar el otro desarrollo: consultar [contexto de integración](contexto-desarrollo.md#integraciones) y [continuidad](contexto-desarrollo.md#continuidad). El usuario confirmó **elegir VLAN existentes**; no crear VLAN nuevas en OPNsense. La referencia aporta un cliente UniFi OS/EFG histórico y reasignación de WLAN existentes, no una implementación de creación de SSID o selección aplicada de AP para portar.

### Comportamiento esperado

Técnicos, operadores y administradores deben poder solicitar nuevos SSID y modificar su distribución después de la carga inicial. La carga CSV no será un requisito para cada cambio posterior: las operaciones individuales usarán el mismo plan, autorización y mecanismo de ejecución que los lotes.

La carga CSV inicial también debe permitir **crear SSID nuevos** para administrador y técnico dentro de sus recursos autorizados. Es un objetivo pendiente: el contrato implementado de CSV continúa restringido a admin y a reservas locales hasta que se desarrollen y prueben los permisos por recurso y el aprovisionamiento común. No habilitarlo solamente cambiando un botón o una política de prompt.

Ejemplo: «Crea Feria-Clientes en los AP Hall y Sala Norte, usando la VLAN 120 del evento Feria». Netbot consulta el inventario autorizado, solicita los datos faltantes y muestra una propuesta con el sitio, evento, nombre del SSID, VLAN exacta, AP seleccionados y perfil de seguridad. El usuario confirma la propuesta desde la interfaz. La respuesta final distingue confirmación, ejecución y verificación.

También debe admitir cambiar los AP de un SSID existente o cambiar su asociación de VLAN, mostrando la configuración anterior y la propuesta. No debe cambiar contraseñas, otros SSID ni la configuración global del AP como efecto implícito.

### Roles y ámbito

| Perfil | Capacidad objetivo |
|---|---|
| Invitado | Orientación, recuperación de su QR y portal abierto; sin inventario técnico ni cambios. |
| Cliente | Soporte y acceso a sus redes asignadas; sin operaciones de infraestructura. |
| Visor | Consulta; sin propuestas ejecutables ni confirmación. |
| Técnico / operador | Consultar inventario y solicitar, confirmar y seguir cambios dentro de sus recursos autorizados. |
| Administrador | Operaciones técnicas en los ámbitos administrados y gestión de asignaciones. No recibe acceso a conversaciones privadas de terceros. |

No basta con añadir `changes:execute` al técnico. Antes de permitir nuevas redes se requiere una asignación explícita de ámbito de aprovisionamiento (sitio/evento) y los AP/VLAN autorizados. Las asignaciones actuales por red no otorgan automáticamente control sobre todo un sitio ni sobre todos los SSID de un AP compartido. La ausencia de una asignación deniega el recurso.

La política debe filtrar el inventario antes de enviarlo al modelo y comprobar actor activo, permisos y recursos al consultar, preparar, confirmar y ejecutar. Una revocación debe impedir un trabajo aún no ejecutado. Los nombres aportados en texto no son identificadores autorizados.

### Selección de recursos y datos del plan

- Tipo de operación: crear SSID o actualizar la asociación de VLAN/AP de uno existente.
- Sitio y evento autorizados, mediante IDs resueltos por el servidor.
- SSID nuevo o ID del SSID existente; nombres ambiguos requieren selección explícita.
- VLAN seleccionada por identidad de red del controlador, etiqueta y correspondencia con la interfaz/VLAN del firewall. El número de VLAN por sí solo no basta entre sitios.
- Lista explícita de AP. No usar «todos» como valor por defecto ni permitir AP de otro ámbito.
- Perfil de seguridad y referencia autorizada al secreto. Las contraseñas se reciben en un formulario protegido, nunca en chat, herramientas, historial ni auditoría.
- Motivo, relación opcional con una fila CSV/reserva confirmada y versión de la configuración de origen.
- Fuente del inventario, instante de lectura, vencimiento del plan y marca de simulación cuando corresponda.

El plan debe comprobar existencia de AP/red, compatibilidad de seguridad, límites del SSID, duplicados y conflictos con cambios pendientes. La conectividad VLAN entre AP, switches y gateway debe verificarse cuando exista telemetría suficiente. No asumirla por el mero hecho de que la VLAN figure en un inventario.

### Flujo compartido de cambios individuales y CSV

1. Consultar inventario y recursos permitidos en el controlador.
2. Preparar una propuesta tipada, sin escrituras de infraestructura ni commits desde herramientas del LLM.
3. Presentar el detalle y diferencias para revisión. Confirmar corresponde a una solicitud API explícita, vinculada al actor, la versión y el contenido exacto del plan.
4. Persistir un trabajo durable e idempotente con su plan aprobado y estado. Revalidar inventario y permisos; si cambió el plan o la configuración, pedir una nueva revisión.
5. Ejecutar mediante un adaptador de la versión de UniFi objetivo. Registrar identificadores externos y cada transición sin secretos.
6. Consultar al controlador y verificar la asociación SSID/red/VLAN y el conjunto exacto de AP. Una respuesta HTTP satisfactoria no equivale a verificación del despliegue ni prueba acceso a Internet.
7. Entregar un resultado verificable: completado, fallido, parcialmente aplicado o pendiente de conciliación. Si falla, compensar únicamente recursos creados por ese trabajo o restaurar la configuración anterior cuando sea seguro; no borrar redes preexistentes o compartidas.

Un reinicio del proceso no debe perder el trabajo ni repetir a ciegas una escritura cuyo resultado sea incierto. Las operaciones dudosas se concilian consultando el controlador antes de reintentar. Los trabajos sobre un mismo SSID o recurso incompatible deben tener control de concurrencia.

Las reservas CSV existentes se mantienen como antecedente local. Una reserva no se marca como «SSID desplegado». El resultado del aprovisionamiento se registra aparte y por operación, conservando los fallos parciales de un lote.

### Integración del chat y de la interfaz

Herramientas objetivo: consultar AP/VLAN/SSID autorizados, preparar creación o modificación y consultar el estado de trabajos propios/autorizados. No exponer herramientas de escritura directa al modelo.

La interfaz presenta una tarjeta de propuesta con AP, VLAN, seguridad y diferencias; permite confirmar o cancelar. Un panel conserva el seguimiento del trabajo después de recargar. La selección de AP y VLAN también debe estar disponible con controles del formulario para resolver ambigüedades del lenguaje natural. Las respuestas tardías de otra sesión o conversación se descartan.

La política del técnico y del administrador se actualizará cuando existan esas herramientas. Hasta entonces el asistente debe seguir indicando que la ejecución no está habilitada, evitando prometer una capacidad que no tiene.

### Decisiones de integración pendientes

1. Versión exacta de UniFi Network, tipo de controlador y API disponible. Con ello se fija el contrato del adaptador y se valida la selección individual/grupal de AP.
2. Correspondencia de inventario: identificar cómo se relacionan las VLAN existentes de OPNsense con las Networks UniFi del sitio. La elección de usar VLAN existentes ya está confirmada; creación de VLAN, DHCP, firewall y direccionamiento nuevo queda fuera de este bloque.

No se usarán claves ni se modificarán equipos reales para resolver estas decisiones. El proveedor simulado debe identificarse como simulación y no sustituye la validación contra el controlador objetivo.

### Criterios de aceptación

- Un técnico autorizado crea un plan de SSID sobre AP y VLAN de su ámbito y lo confirma; invitados, clientes y visores no pueden hacerlo ni manipulando la API.
- AP/VLAN/SSID ajenos son rechazados antes de cualquier escritura y no aparecen en el contexto del modelo.
- La selección de AP es exacta: no se amplía automáticamente a todo el sitio.
- Una modificación muestra y valida la versión anterior; un plan vencido o alterado no se ejecuta.
- Reintentar la confirmación o reiniciar un worker no duplica SSID ni repite escrituras inciertas.
- Revocar permisos o recursos bloquea los trabajos pendientes.
- Fallos parciales, verificación y compensación conservan la trazabilidad y los recursos preexistentes.
- Un cambio individual posterior al CSV no obliga a volver a cargar todo el archivo ni modifica filas ajenas.
- Los secretos nunca aparecen en prompts, historial, respuestas de herramientas, logs ni auditoría.

### Referencias

La guía oficial [Creating UniFi WiFi SSIDs](https://help.ui.com/hc/en-us/articles/26136823938583-Creating-UniFi-WiFi-SSIDs) describe asociar el SSID a una red y elegir AP específicos o grupos; también exige permitir la VLAN en los puertos entre los AP y el gateway. La [referencia de ajustes Wi-Fi](https://help.ui.com/hc/en-us/articles/32065480092951-UniFi-WiFi-SSID-and-AP-Settings-Overview) distingue difusión por todos los AP, selección específica y grupos. Estos conceptos funcionales no reemplazan el contrato de la API de la versión instalada.


<a id="evidencias"></a>

## Matriz de evidencia

Snapshot: `diktya-atlas@6403ab0e1cb72141a3df6b51091a560f89254fd7`. Las rutas de esta matriz son relativas a **ese repositorio**, no a Netbot. Son localizadores para revisar procedencia; Netbot no debe importar archivos de allí ni depender de que esté disponible al ejecutar o probar. Revisión estática del 29 de octubre de 2026. No se corrieron sus pruebas, workers, servidor, seeds, migraciones ni llamadas de red.

Clasificación: **C** código seguido hasta su llamador; **T** contenido de pruebas inspeccionado; **H** afirmación histórica de documentación/comentarios, no reproducida; **D** decisión explícita del usuario para Netbot; **R** recomendación derivada, no capacidad implementada.

### Integraciones y arquitectura

| ID | Evidencia y conclusión acotada | Tipo | Localizador en la referencia |
|---|---|---|---|
| E01 | Monorepo TypeScript: Fastify, Prisma, PostgreSQL, Redis/BullMQ; frontend React/Vite. Los manifiestos declaran paquetes, no demuestran despliegue sano. | C | `package.json`, `pnpm-workspace.yaml`, `apps/backend/package.json`, `apps/frontend/package.json` |
| E02 | Se distinguen Integration API, sesión clásica y transporte cloud. Construcción directa/conector y normalización de prefijo. | C/T | `apps/backend/src/integrations/unifiOs/client.ts`: `direct`, `viaConnector`, `resolvePath`, `stripProxyPrefix`; `apps/backend/test/unifiOsClient.connector.test.ts` |
| E03 | Operaciones de listado paginado; detalle y PUT directos; acciones sin cuerpo. El sitio tiene un camino de lectura diferente. | C | `apps/backend/src/integrations/unifiOs/client.ts`: `requestJson`, `request`, `requestVoid`, `requestAllPages`, `listSites` |
| E04 | El sitio configurado se resuelve por `internalReference`; el UUID queda cacheado. Pasar otro `sitio` a ciertos métodos no selecciona por sí mismo otro sitio remoto. | C/R | `apps/backend/src/integrations/unifiOs/client.ts`: `resolveSiteId`; `apps/backend/src/integrations/unifi/liveClient.ts`: `getIntegrationSiteId`, `listNodes`, `listWifiNetworks` |
| E05 | El cliente combina devices, clientes, broadcasts y estadísticas; tolera fallo de estadísticas por equipo. | C/T | `apps/backend/src/integrations/unifi/liveClient.ts`: `listNodes`; `apps/backend/test/unifiLiveClient.integrationApi.test.ts` |
| E06 | El enlace broadcast→Network resuelve la VLAN; red nativa puede omitir el campo. Features/estados/bandas requieren normalización. Hay defaults del origen que no conviene usar para datos no resolubles. | C/T/H | `apps/backend/src/integrations/unifi/normalize.ts`; `apps/backend/src/integrations/unifiOs/client.ts`: tipos de broadcast; `apps/backend/test/normalize.test.ts` |
| E07 | La difusión individual usa `DEVICES`; los tags no se resuelven. No hay operación para seleccionar nuevos AP en el contrato de escritura de alto nivel revisado. | C | `apps/backend/src/integrations/unifiOs/client.ts`: `UnifiOsBroadcastingDeviceFilter`; `apps/backend/src/integrations/unifi/liveClient.ts`: `listNodes`, `writeWifiNetwork`; `apps/backend/src/integrations/unifi/client.ts`: `WriteWifiNetworkInput` |
| E08 | Escritura real limitada a WLAN y Network existentes. Lee detalle completo y cambia red/bandas. Crear cualquiera de esos recursos produce rechazo explícito. | C/T | `apps/backend/src/integrations/unifi/liveClient.ts`: `writeWifiNetwork`; `apps/backend/src/integrations/unifi/client.ts`: error de operación no soportada; `apps/backend/test/unifiLiveClient.integrationApi.test.ts` |
| E09 | Reinicio usa acción por ID; adopción por MAC tiene implementación pero no se acredita conservación de configuración en hardware. | C/T/H | `apps/backend/src/integrations/unifiOs/client.ts`: `executeDeviceAction`, `adoptDevice`, `listPendingDevices`; `apps/backend/src/services/autoRemediation.service.ts`; pruebas del cliente Integration API |
| E10 | Alarmas siguen un camino clásico no validado según comentarios; no constituyen una integración universal probada. | C/H | `apps/backend/src/integrations/unifi/liveClient.ts`: `login`, `request`, `listAlerts` |
| E11 | OPNsense directo usa Basic key/secret y consulta sistema/gateways. Escrituras, Wi-Fi y reboot lanzan no implementado. La petición directa no configura timeout. | C | `apps/backend/src/integrations/opnsense/client.ts`; `apps/backend/src/integrations/opnsense/liveClient.ts`: `request`, `listNodes`, `listAlerts`, métodos no implementados |
| E12 | La fuente declara validación de lectura en una consola UniFi OS/EFG y un firewall, en fechas históricas. No se reproduce ni se establece la versión actual de Network. | H | `Atlas/OPNsense y UniFi.md`; `Atlas/Infraestructura Real.md`; comentarios de clientes live |
| E13 | La arquitectura posterior prescribe consumir ATLAS. Las notas también reconocen rutas directas aún pendientes de migrar; es una transición parcial. | H/C | `Atlas/ARGOS Arquitectura y Entrega 2026-08-10.md`; `Atlas/ATLAS — Rutas faltantes para ARGOS.md`; `apps/backend/src/workers/worker-monitor.ts`; `apps/backend/src/services/network.service.ts` |
| E14 | Inventario y estado del firewall consumen el intermediario; diagnóstico, listado Wi-Fi y otros flujos conservan dependencias directas UniFi. | C | `apps/backend/src/services/opnsense.service.ts`; `apps/backend/src/workers/worker-monitor.ts`; `apps/backend/src/services/network.service.ts`; `apps/backend/src/workers/remediation.logic.ts` |
| E15 | El cliente intermediario tiene lecturas por familias, headers inyectables y timeouts diferenciados; no controla infraestructura. | C/T | `apps/backend/src/integrations/atlas/client.ts`; `apps/backend/src/integrations/atlas/types.ts`; `apps/backend/test/atlasClient.test.ts` |
| E16 | HTTP 200 puede contener `ok:false`. HA y detalles históricos cambian de forma. Se requieren validación semántica y soporte de variantes documentadas. | C/T/H | `apps/backend/src/integrations/atlas/types.ts`; `apps/backend/src/integrations/atlas/normalize.ts`; `apps/backend/test/atlasNormalize.test.ts`; nota de arquitectura del 10 de agosto |
| E17 | El intermediario no ofrece identidad inmutable completa ni métricas por AP equivalentes; el normalizador usa nombre, cero/lista vacía y hora actual en algunos campos. | C/H/R | `apps/backend/src/integrations/atlas/normalize.ts`: `atlasEquipoToNetworkNode`; nota de arquitectura del 10 de agosto. Netbot debe representar explícitamente desconocido y diferenciar timestamps. |
| E18 | Existen clientes separados para Mobility, Site Manager y Proxmox. No implican permisos ni capacidades equivalentes a Network. | C | `apps/backend/src/integrations/mobility/client.ts`; `apps/backend/src/integrations/siteManager/client.ts`; `apps/backend/src/integrations/proxmox/client.ts` |

### Cambios, chat y seguridad

| ID | Evidencia y conclusión acotada | Tipo | Localizador en la referencia |
|---|---|---|---|
| E19 | El CSV de referencia tiene otro contrato; genera diff y planes temporales. La detección de «sin cambios» compara VLAN, no todos los atributos operativos. | C | `packages/shared/src/vlan.ts`; `apps/backend/src/services/csvIngestion.service.ts`; `apps/backend/src/services/planDiff.service.ts` |
| E20 | Reservas se persisten y la aplicación encola trabajos con reintentos. Existe snapshot del plan, pero eso por sí solo no prueba propiedad, aprobación o reautorización al ejecutar. | C/R | `apps/backend/src/services/vlanFlow.service.ts`; `apps/backend/src/services/vlanReservation.service.ts`; `apps/backend/src/workers/queues.ts`; `apps/backend/src/routes/vlan.ts` |
| E21 | Restricción única por VLAN/sitio/estado en Prisma, no un índice parcial solo de activos. No trasladarla a Netbot como solución de reservas históricas. | C/R | `apps/backend/prisma/schema.prisma`: `VlanReservation`; `apps/backend/src/services/vlanReservation.service.ts` |
| E22 | Lock distribuido por sitio/VLAN y baseline comparado antes de escribir. El baseline no compara todos los atributos y el lock no cubre por sí solo un mismo SSID movido a dos VLAN distintas. | C/R | `apps/backend/src/services/lock.service.ts`; `apps/backend/src/workers/remediation.logic.ts`: `processRemediation` |
| E23 | Relectura posterior compara SSID/VLAN/bandas y ensaya rollback; no cubre AP exactos ni toda la configuración de seguridad. Casos no soportados generan ticket en vez de reintento transitorio. | C | `apps/backend/src/services/writeVerification.service.ts`; `apps/backend/src/workers/remediation.logic.ts` |
| E24 | E2E crea un SSID con mock y llama al procesador directamente; no prueba creación real ni una aprobación humana emitida por la UI. | T | `apps/backend/test/e2e-csv-to-apply.test.ts`; `apps/backend/src/integrations/unifi/mockClient.ts` |
| E25 | El LLM recibe herramientas filtradas por rol y hay validación server-side; las herramientas incluyen reservar y encolar aplicación. | C/T | `packages/shared/src/tools.ts`; `apps/backend/src/llm/tools/registry.ts`; `apps/backend/src/llm/tools/executor.ts`; `apps/backend/test/toolRegistry.test.ts` |
| E26 | La propia nota identifica que el modelo puede encadenar propuesta/reserva/aplicación sin pasar por la tarjeta. El código no contiene en esa cadena una prueba de aprobación vinculada al plan. | H/C | `Atlas/LLM y tools.md`: gap de confirmación; `apps/backend/src/routes/chat.ts`; `apps/backend/src/llm/tools/executor.ts`; `apps/backend/src/routes/vlan.ts` |
| E27 | El chat de referencia acepta historial del navegador y devuelve resultados de herramientas; no es el modelo de historial privado persistente de Netbot. | C | `apps/backend/src/routes/chat.ts`; `apps/frontend/src/chat/ChatContext.tsx` |
| E28 | Roles de referencia son ADMIN/TECNICO/VISUALIZADOR; no equivalen al alcance por redes asignadas y al invitado académico. Los jobs revisados no transportan una aprobación por actor ni revalidan sus permisos al ejecutar. | C/R | `packages/shared/src/roles.ts`; `apps/backend/src/auth/middleware.ts`; `apps/backend/src/workers/queues.ts`: `RemediationJobData`; `apps/backend/src/workers/remediation.logic.ts` |
| E29 | Auth incluye sesiones y rotación; el frontend deduplica renovación. El fallback por headers de desarrollo se desactiva en producción. No incorporarlo como bypass en Netbot. | C/T | `apps/backend/src/auth/session.service.ts`; `apps/backend/src/auth/middleware.ts`; `apps/backend/src/config/env.ts`; `apps/frontend/src/auth/AuthContext.tsx`; `apps/frontend/src/lib/apiClient.ts`; pruebas de sesión/AuthContext |
| E30 | El hub redistribuye eventos globales y la ruta WebSocket revisada no autentica clientes. El checklist no equivale a haberlo corregido. | C/H | `apps/backend/src/app.ts`: registro de `/ws`; `apps/backend/src/realtime/hub.ts`; `SECURITY.md` |
| E31 | Configuración y notas de TLS/booleans tienen decisiones y comentarios históricos; el esquema coercitivo documenta el caso string `false`. No trasladar defaults inseguros. | C/H/R | `apps/backend/src/config/env.ts`; Netbot ya tiene configuración Pydantic, CA y errores TLS propios. |
| E32 | WhatsApp, entrega individual y vouchers figuran como diseño pausado, no implementación. Las afirmaciones de disponibilidad/costo de API del documento son históricas, no verificadas hoy. | H | `Atlas/WhatsApp y credenciales de invitados.md` |

### Operación y funciones adyacentes

| ID | Evidencia y conclusión acotada | Tipo | Localizador en la referencia |
|---|---|---|---|
| E33 | Sincronización persiste estado, emite eventos y registra cambios. Disponibilidad excluye el periodo sin datos en vez de considerarlo caída. | C/T | `apps/backend/src/services/nodeSync.service.ts`; `apps/backend/src/services/nodeAvailability.service.ts`; `apps/backend/test/nodeAvailability.service.test.ts` |
| E34 | Auto-remediación tiene límites por tipo, cooldown, relectura y escalamiento. Distingue recuperación espontánea de éxito de reset; readopción exige revisión de configuración. No es una función autorizada para incorporar ahora. | C/T/H/R | `apps/backend/src/services/autoRemediation.service.ts`; `apps/backend/src/services/nodeSync.service.ts`; `apps/backend/test/autoRemediation.service.test.ts`; `apps/backend/test/autoRemediation.eligibility.test.ts` |
| E35 | Recinto/evento/zona/plano/calibración/AP colocado forman un modelo independiente de la difusión real. Cobertura calculada es geométrica, no medición RF. | C/T/H | `apps/backend/src/services/coverage.service.ts`; `apps/backend/src/services/apPlacement.service.ts`; `apps/backend/src/services/eventZone.service.ts`; `apps/backend/test/coverage.service.test.ts`; `Atlas/Mapeo de planos y cobertura.md` |
| E36 | Archivos persistidos requieren volumen y backup independiente de la base; hay artefactos de backup en el último commit. No se ejecutaron ni se verificó una restauración. | C/H | `apps/backend/src/services/fileStorage.service.ts`; `docker-compose.prod.yml`; `deploy/backup.sh`; `DEPLOY.md` |
| E37 | Hay canales Telegram/Slack/webhook; email es stub. El servicio tolera fallos por canal y no equivale a prueba de entrega al destinatario. | C | `apps/backend/src/services/notification.service.ts` |
| E38 | La operación sin WAN es requisito histórico del despliegue de referencia; las notas reconocen pendientes. No se acredita cumplimiento con solo tener Compose o una VM. | H/C/R | `Atlas/ARGOS Arquitectura y Entrega 2026-08-10.md`; `Atlas/Despliegue a Producción.md`; `docker-compose.prod.yml`; timeouts de proveedores/notificaciones |
| E39 | No se identificó LICENSE/LICENCE/COPYING/NOTICE en los archivos versionados del snapshot. Los manifiestos marcan paquetes privados. No se deduce de ello autorización para portar el producto. | C | Inventario del árbol Git y manifiestos del snapshot. La revisión se limita a síntesis técnica por instrucción del autor. |
| E40 | Para Netbot se eligen VLAN existentes; no se crean VLAN nuevas en OPNsense en el siguiente bloque. | D | Respuesta explícita del usuario el 29 de octubre de 2026. |
| E41 | El setup de pruebas del origen documenta una contaminación previa de reportes por usar servicios reales. Cambia nombre de base e índice Redis, pero eso no crea por sí solo servicios de prueba independientes. No se ejecutó. | C/H/R | `apps/backend/test/setup.ts`; `apps/backend/test/e2e-csv-to-apply.test.ts`. Para Netbot usar servicios/credenciales y datos de laboratorio aislados. |

### Contradicciones que deben permanecer visibles

1. El README raíz conserva «OPNsense real pendiente», pero existe un cliente directo y luego se migró parte de la lectura al intermediario. Describir por componente y camino, no con un sí/no global.
2. Comentarios antiguos dicen que la Integration API no tiene WLAN; el cliente y las pruebas revisadas sí usan Wi-Fi Broadcasts. Una nota sobre alarmas no prueba que falten todos los endpoints Wi-Fi.
3. La arquitectura prescribe una sola fuente intermediaria; el grafo real mantiene dependencias directas. No convertir un «prohibido» documental en una garantía de que no puede ejecutarse.
4. El mock admite creación, el cliente real la rechaza. Un diff `crear` no acredita capacidad de ejecutar la creación.
5. La UI habla de confirmación, el bucle de herramientas puede evitarla. Netbot debe probar la barrera del servidor.
6. Comentarios de reinicio manual dicen que no hay worker llamador, mientras auto-remediación sí usa reinicio directo con sus propias condiciones.

Para actualizar el conocimiento en el futuro: registrar nuevo commit, inspeccionar el camino completo, distinguir prueba mock/laboratorio y modificar esta matriz antes de cambiar las conclusiones de las otras guías. No actualizar IPs o claves en este paquete documental.


<a id="organizacion"></a>

## Organizacion documental

Acuerdo de trabajo del 29 de octubre de 2026. El propósito es separar documentación de trabajo y entregables académicos, preservar su trazabilidad y evitar cambios accidentales en la estructura de entrega. La estructura exacta exigida por la institución está pendiente de incorporar; este documento no atribuye a la guía requisitos que no se hayan comprobado.

### Función de las ramas

| Rama | Responsabilidad |
|---|---|
| `feature/*` | Cambios de una tarea y sus verificaciones. Destino habitual de integración: `dev`. |
| `dev` | Integración del desarrollo y ubicación de mantenimiento de las guías internas, contexto y propuestas. |
| `main` | Versión de entrega revisada, con código, documentación técnica y evidencias exigidas por la institución. |

Mantener y actualizar las instrucciones internas en `dev` o en una rama de trabajo que se integre a `dev`. No crear commits directamente en `main` para actualizar instrucciones internas. Antes de promover una versión a `main`, revisar la clasificación de los archivos y el alcance de la entrega; no trasladar automáticamente todo el material de trabajo de `dev`.

### Clasificar por finalidad, no por extensión

| Documentación | Tratamiento |
|---|---|
| `AGENTS.md`, `CLAUDE.md` y contexto de trabajo para asistentes | Mantenimiento en el flujo de desarrollo de `dev`; revisar su presencia en una promoción a `main` conforme al manifiesto de entrega aprobado. |
| Síntesis externa, matrices de revisión y propuestas aún no implementadas | Material de trabajo de `dev`; conservar procedencia y límites. Si se necesita como evidencia académica, preparar la referencia o anexo correspondiente. |
| README, instalación, arquitectura implementada, contratos, seguridad y operación | Documentación técnica del producto. Debe acompañar a la versión entregada cuando corresponda. |
| Informes, evidencias individuales/grupales, atribuciones, licencias y declaración de herramientas/aportes que se exijan | Conservar según los requisitos institucionales y del proyecto. No excluirlos por ser documentación de desarrollo o mencionar herramientas. |

No prohibir globalmente archivos `*.md` en `main`. Tampoco usar la presencia de referencias a IA como criterio de eliminación: la clasificación depende de la función del documento y de los requisitos de la entrega.

### Situación actual y límites

`main` ya contiene `AGENTS.md`, `CLAUDE.md` y otras guías en su historial y árbol versionado. La política de mantenimiento en `dev` no borra esos archivos ni cambia retroactivamente los commits. Esta actualización no elimina archivos de ninguna rama, no reescribe historial y no modifica evidencias académicas.

Una rama de Git contiene un árbol completo. Un merge de `dev` a `main` puede llevar todos sus archivos versionados; Git no reconoce esta clasificación documental. `.gitignore` no afecta archivos ya versionados y no constituye un filtro por rama. Esta política es una instrucción de revisión, no una protección técnica instalada en GitHub.

La selección final de documentos de entrega requiere un manifiesto que enumere las rutas y su justificación institucional. No generar automáticamente una rama depurada, borrar documentos o añadir filtros de exportación hasta conocer ese manifiesto. Las referencias internas del README y demás documentos deben seguir funcionando en la versión que se entregue.

### Revisión antes de promover una entrega

1. Identificar la versión del código y la guía/rúbrica aplicable. Incorporar el apartado exacto de estructura cuando esté disponible.
2. Comparar los cambios de `dev` con `main`, incluyendo documentación, migraciones y archivos nuevos. Revisar el árbol resultante, no solo el nombre de los commits.
3. Elaborar y revisar el manifiesto de entrega: código, instalación, arquitectura, contratos, evidencias y documentación requerida. Separar el material interno por finalidad y conservarlo en desarrollo.
4. Comprobar enlaces de la documentación, instrucciones ejecutables y pruebas pertinentes a la versión del código. No dejar enlaces a archivos que no acompañen la entrega sin indicar dónde se conservan.
5. Revisar que no haya secretos, datos personales del cliente, entornos virtuales, caches o archivos temporales incorporados accidentalmente.
6. Integrar y publicar solo el alcance autorizado por el usuario. Conservar el historial y las declaraciones de procedencia/herramientas que correspondan.

### Requisitos aún por verificar

Se consultó el texto de las guías Word de definición de Fase 1, desarrollo de Fase 2 e informe final de Fase 2 presentes en el repositorio. No se localizó allí una especificación explícita de ramas o exclusión de Markdown. Puede existir en otro apartado, imagen, rúbrica o instrucción del docente. No reorganizar `Fase 1/`, `Fase 2/`, `Arquitectura/` o `netbot/` basándose en una estructura supuesta.
