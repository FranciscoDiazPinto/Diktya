# Diseño: chatbot de monitoreo para Netbot

**Fecha:** 2026-10-21  
**Rama:** `feature/chatbot`  
**Estado:** diseño aprobado

## Objetivo

Agregar una primera versión de chatbot en español para que usuarios autenticados consulten el estado de la red de Netbot usando un modelo de OpenRouter. El chatbot podrá responder preguntas de monitoreo con datos actuales del `MonitoringService` y estará limitado al dominio de redes y de la aplicación Netbot.

La primera entrega incluye un endpoint de API y un panel sencillo integrado al dashboard existente. No ejecutará cambios ni otras tareas que modifiquen la red.

## Roles y permisos

| Rol | Puede conversar | Puede consultar monitoreo | Puede ejecutar acciones |
| --- | --- | --- | --- |
| `visor` (usuario base) | Sí | Sí | No en esta entrega |
| `operador` (técnico) | Sí | Sí | No en esta entrega |
| `admin` | Sí | Sí | No en esta entrega |

El permiso `CHAT_USE` se agregará a `VISOR`; `OPERADOR` ya lo tiene y `ADMIN` recibe todos los permisos. El endpoint exigirá autenticación y `CHAT_USE`. Antes de invocar cada herramienta, el backend comprobará el permiso requerido por esa herramienta. Para las herramientas de esta entrega será `MONITORING_READ`.

Los nombres de rol y permisos del usuario se obtienen de la sesión autenticada en el servidor. No se aceptarán roles, permisos ni identidad enviados por el cliente o inferidos por el modelo.

## Enfoque elegido

El backend ofrecerá al modelo un conjunto cerrado de herramientas de solo lectura. El modelo podrá pedir una consulta de monitoreo; la aplicación validará el nombre y argumentos, comprobará autorización, ejecutará la consulta mediante el servicio existente y devolverá al modelo solo la respuesta normalizada necesaria para redactar una explicación.

No se expondrán herramientas genéricas, acceso a shell, SQL, HTTP arbitrario, credenciales de OPNsense ni llamadas directas a dispositivos. El modelo no podrá inventar herramientas ni ejecutar código. Las futuras acciones de escritura deberán definirse como herramientas explícitas, cada una asociada a su permiso y reglas de confirmación.

## Componentes

### API de chat

Se agregará `POST /api/v1/chat/messages`, protegido por JWT y `CHAT_USE`. El cuerpo recibirá el mensaje actual y, si se usa contexto conversacional, una lista acotada de turnos previos del usuario y el asistente. El servidor descartará roles o mensajes de sistema/herramienta que el cliente intente aportar.

La respuesta incluirá el texto del asistente y, cuando corresponda, metadatos no sensibles de las consultas realizadas. No expondrá razonamiento interno, prompts del sistema, cabeceras de OpenRouter ni secretos.

### Servicio conversacional

Un servicio de aplicación coordinará la validación del mensaje, las reglas de alcance, las llamadas al proveedor LLM y la ejecución de herramientas permitidas. Las funciones de cada herramienta serán adaptadores pequeños sobre `MonitoringService`, manteniendo el acceso a OPNsense y sus datos normalizados dentro del módulo de monitoreo.

Las herramientas iniciales cubrirán:

- estado del sistema;
- estado y métricas de interfaces;
- clientes DHCP;
- estadísticas del firewall;
- eventos del firewall con límite y filtros admitidos por el servicio.

### Proveedor OpenRouter

La integración se encapsulará detrás de un adaptador. Se configurará mediante variables de entorno, como mínimo `OPENROUTER_API_KEY` y `OPENROUTER_MODEL`. Se reutilizará `httpx`, ya presente en las dependencias, salvo que la implementación revele una razón concreta para otra opción.

La clave solo estará en el backend; no se incluirá en archivos versionados ni en el frontend. El tiempo de espera, errores y respuestas inválidas del proveedor se manejarán sin mostrar secretos o cuerpos sensibles al usuario.

### Panel web

El dashboard existente incorporará un panel sencillo de conversación con campo de entrada, envío, historial de la sesión, indicador de espera y presentación legible de errores. El cliente usará el token de acceso ya almacenado por el flujo de login. No se rediseñará el dashboard en esta entrega.

El historial vivirá únicamente en memoria durante la sesión del navegador. No habrá persistencia de conversaciones en la base de datos; al recargar o cerrar el navegador se perderá.

## Alcance temático y seguridad

El asistente debe responder en español, dentro del contexto de redes, monitoreo y uso de Netbot. Debe rechazar preguntas ajenas a ese contexto, no fingir datos de la infraestructura y aclarar cuando el monitoreo no entregue información o esté degradado.

La aplicación aplicará defensa en profundidad: instrucciones explícitas de sistema, límite de contexto, herramientas exclusivamente relacionadas con redes, validación de argumentos y ausencia de acceso general a Internet o herramientas arbitrarias. El contenido del usuario y los datos de red se tratarán como datos no confiables, no como instrucciones que puedan reemplazar la política del sistema.

La restricción de tema es una política conversacional, no una garantía formal de que un modelo generativo nunca producirá una frase fuera de tema. Si se requiere una garantía estricta, se necesitaría un control semántico adicional independiente antes y después de la generación, con el costo y los falsos positivos correspondientes. Ese control queda fuera de esta primera entrega.

Las respuestas deben apoyarse en resultados actuales de herramientas cuando afirmen el estado de la infraestructura. Si no consultaron datos o la consulta falla, deben decirlo explícitamente en lugar de presentar una inferencia como un hecho.

## Flujo de una conversación

1. El usuario inicia sesión y envía un mensaje desde el panel.
2. El endpoint valida JWT, estado activo de la cuenta y `CHAT_USE`.
3. El servicio valida el tamaño del mensaje y del historial, y aplica el contexto de Netbot.
4. El proveedor OpenRouter recibe el mensaje y las herramientas de solo lectura disponibles.
5. Si el modelo solicita una herramienta, el backend valida la herramienta y sus argumentos, comprueba `MONITORING_READ` y consulta `MonitoringService`.
6. El resultado normalizado se devuelve al modelo; el proveedor redacta una respuesta acotada al resultado.
7. El endpoint devuelve la respuesta al panel. El cliente conserva los turnos en memoria para las siguientes preguntas.

El número de rondas de herramientas por mensaje tendrá un máximo configurable o constante pequeña para evitar bucles. El servidor limitará el tamaño de mensajes, historial y respuesta.

## Errores

- Sin sesión o token válido: respuesta de autenticación de la API.
- Usuario sin `CHAT_USE`: `403` antes de llamar a OpenRouter o al monitoreo. Si falta el permiso de una herramienta, el backend no ejecutará esa herramienta y devolverá un error controlado.
- Clave/modelo no configurado: error de servicio claro, sin iniciar una llamada externa.
- Timeout, límite o indisponibilidad de OpenRouter: error controlado que permita reintentar y no revele datos internos.
- Monitoreo no disponible o degradado: el asistente informará esa condición usando el formato de `MonitoringResponse`.
- Nombre de herramienta, argumentos o estructura de respuesta inválidos: rechazo controlado y registro técnico sin secretos.

## Fuera de alcance

- Reservar VLAN, crear tickets, aprobar/ejecutar cambios o modificar reglas de firewall.
- Agente autónomo con planificación abierta, acceso a Internet, shell o herramientas no declaradas.
- Persistencia de usuarios, sesiones o transcripciones del chatbot.
- Cambio del sistema de autenticación o creación de roles nuevos.
- Garantía formal de clasificación temática perfecta.
- Rediseño del dashboard.

## Criterios de aceptación

1. `visor`, `operador` y `admin` autenticados pueden conversar y consultar las herramientas de monitoreo permitidas.
2. Un usuario no autenticado o sin `CHAT_USE` no puede usar el endpoint.
3. El modelo no puede ejecutar una herramienta que no esté en la lista cerrada; cada solicitud de herramienta se valida y autoriza en el backend.
4. Una petición para modificar la red no produce cambios y recibe una explicación de que esa capacidad aún no está disponible.
5. Preguntas ajenas al dominio reciben una negativa breve que devuelve la conversación a redes/Netbot.
6. Las respuestas que describan el estado actual reflejan los datos o errores devueltos por `MonitoringService`.
7. El panel usa la sesión autenticada, muestra espera y errores, y no contiene la clave OpenRouter.
8. El historial no se guarda en la base de datos y se limita antes de enviarlo al proveedor.
9. Los errores del proveedor no exponen claves, cabeceras, prompts internos ni cuerpos sensibles.

## Preguntas resueltas

- `visor` es el rol de usuario base; `operador` representa al técnico.
- El primer corte cubre solo consultas de monitoreo.
- La primera entrega incluye API y un panel sencillo integrado al dashboard.
- Las conversaciones no se persistirán inicialmente.
