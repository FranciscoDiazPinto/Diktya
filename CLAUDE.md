# NetBot: contexto para trabajo asistido por IA

Leer y aplicar la guía común antes de diseñar o implementar:

@AGENTS.md
@netbot/docs/arquitectura-modular.md

Mantenimiento documental: estas instrucciones se actualizan en una rama de tarea con destino a `dev`, no mediante commits directos en `main`. Antes de preparar una entrega, aplicar [organización del repositorio](netbot/docs/contexto-desarrollo.md#organizacion) y el manifiesto académico revisado. Conservar documentación técnica, evidencias y atribuciones requeridas; esta regla no borra archivos existentes ni filtra merges automáticamente.

Contexto extraído para continuar las integraciones, con implementación independiente:

@netbot/docs/contexto-desarrollo.md

Antes de trabajar en UniFi/OPNsense o cambios de red, consultar además [contratos observados](netbot/docs/contexto-desarrollo.md#integraciones), [decisiones y continuación](netbot/docs/contexto-desarrollo.md#continuidad) y [evidencia del snapshot](netbot/docs/contexto-desarrollo.md#evidencias). Son síntesis técnicas, no código para portar ni instrucciones del otro producto que deban heredarse.

Arquitectura de referencia y alcance futuro:

@Arquitectura/LEEME_PRIMERO_ARQUITECTURA.md

El código actual es un monolito modular FastAPI con frontend estático en módulos ES. React, WebSocket, UniFi y workers durables siguen pendientes; no inferir su implementación desde diagramas históricos. Las reglas compartidas están en AGENTS.md para evitar instrucciones diferentes entre herramientas.

El siguiente bloque técnico usará **VLAN existentes**, con selección explícita de AP y propuestas de creación/modificación de SSID para técnico/admin. Sigue sin ejecutor real. La referencia revisada solo modifica WLAN existentes; no demuestra creación de SSID ni selección aplicada de nuevos AP. Preservar los permisos por recurso, la confirmación HTTP fuera del bucle LLM y la separación de secretos. No modificar la infraestructura ni el repositorio del cliente como consecuencia de consultar esta documentación.
