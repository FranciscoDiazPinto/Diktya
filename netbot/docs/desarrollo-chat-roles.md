# Desarrollo del chat por roles

Acuerdo de alcance: 27 de octubre de 2026.

## Orden de implementación

1. Integrar main en feature/chatbot y verificar monitoreo, chat y reservas VLAN.
2. Implementar permisos por recurso y asignaciones cliente/red/sitio/evento; aislar conversaciones.
3. Persistir conversaciones y mensajes en PostgreSQL y probar accesos cruzados.
4. Completar atención al cliente: acceso Wi-Fi propio, estado de su red y tickets.
5. Integrar UniFi para operaciones técnicas, con confirmación, ejecución, verificación y auditoría.
6. Incorporar gestión de usuarios y roles desde el chat de administración.
7. Incorporar carga CSV después de revisar la documentación de la API UniFi objetivo.

## Roles y alcance

- Cliente: consultar únicamente su acceso Wi-Fi y el estado de sus redes asignadas; crear y consultar sus tickets. Sin monitoreo global ni cambios de red.
- Técnico: diagnosticar y gestionar tickets de sus sitios/eventos asignados; reiniciar y adoptar APs, crear SSIDs y aprovisionar VLANs dentro de ese ámbito.
- Administrador: capacidades técnicas y gestión de usuarios, activación y asignación de roles. El acceso a conversaciones ajenas requiere un permiso independiente y auditoría.
- Visor: conservar como rol interno de lectura; no migrarlo automáticamente a cliente.

Los roles definen capacidades; las asignaciones definen los recursos sobre los que pueden usarse. Un permiso global de monitoreo no reemplaza esa comprobación.

## Workers

Un punto de entrada autenticado deriva a cuatro especialidades: atención al cliente, diagnóstico/soporte, operaciones de red y administración. El backend selecciona herramientas según permisos y ámbito, y vuelve a autorizarlas antes de ejecutarlas. El LLM no concede permisos.

Los trabajos que modifican infraestructura requieren almacenamiento persistente de su estado, confirmación asociada al actor y al plan exacto, control de reintentos, verificación y auditoría. El rollback se define por operación; un reinicio no se puede deshacer.

## Conversaciones y datos

- Cada conversación pertenece a un usuario y tiene un ámbito explícito de cliente/evento cuando corresponda.
- El servidor obtiene la identidad de la sesión y carga el historial desde la base de datos; no confía en el historial ni en identificadores de propietario enviados por el navegador.
- Toda lectura, escritura y llamada de herramienta verifica propietario y ámbito.
- Filtrar recursos antes de enviarlos al modelo. No enviar inventarios globales a clientes.
- Técnicos y administradores recuperan sus conversaciones después de recargar o volver a iniciar sesión.
- Entregar credenciales Wi-Fi mediante una respuesta protegida; no incluir secretos en prompts, historial persistente ni logs. Nunca entregar credenciales del controlador o firewall.
- Diferenciar red caída de telemetría no disponible. No inferir disponibilidad solo a partir de una concesión DHCP.

## Criterios de aceptación prioritarios

- Cliente A no puede leer conversaciones, credenciales, redes ni tickets de B, incluso manipulando IDs o instrucciones del chat.
- Cliente no puede invocar herramientas técnicas ni administrativas directamente por API.
- Técnico no puede gestionar usuarios ni operar fuera de sus asignaciones.
- Cambio de rol o desactivación se aplica a las siguientes solicitudes y a la ejecución de trabajos pendientes.
- Administrador no obtiene acceso implícito al historial privado de otros usuarios.
- Historial técnico/admin se conserva tras recarga y nueva sesión, sin mezclar cuentas.
- Una propuesta de reserva local no se presenta como aprovisionamiento real de VLAN o SSID.

## Estado después del bloque de atención al cliente

La integración conserva el dashboard con monitoreo en vivo, el chatbot y las reservas VLAN locales (ahora limitadas a admin). Se implementaron cliente/tecnico, asignaciones por red, conversaciones privadas y persistencia del historial. Operador queda limitado como técnico; visor sigue siendo un rol interno global. Ver [detalle y migración](chat-roles-y-persistencia.md).

Se agregó soporte con entrega protegida de acceso Wi-Fi desde secretos del entorno, diagnóstico acotado por interfaz y tickets persistentes con confirmación y seguimiento. Ver [soporte al cliente](soporte-cliente.md). La disponibilidad completa de SSID/AP/Internet sigue sin poder confirmarse con la fuente actual.

El siguiente bloque es integrar las operaciones técnicas UniFi con permisos por recurso, confirmación, trabajos durables, verificación y auditoría; después, administración por chat. La carga CSV sigue para la etapa posterior acordada.

## Refactorización modular

Se separaron controladores frontend, servicios de autenticación/inventario, autorización por recurso, diagnóstico y credenciales; el chat dejó de consultar tablas de tickets. Arranque, registro de modelos y HTTP tienen composición propia. Las pruebas de arquitectura vigilan esos límites y el arranque migrado de producción. Ver [guía vigente](arquitectura-modular.md).

Este bloque conserva las funcionalidades y los contratos HTTP; no implementa todavía UniFi ni trabajos durables, y no requiere nuevas migraciones.
