# Documentación de Netbot

## Lectura inicial para desarrollo e IA

1. [Guía compartida del repositorio](../../AGENTS.md).
2. [Arquitectura modular vigente](arquitectura-modular.md): módulos, dependencias, contratos, transacciones y extensión.
3. [Inicio local y comandos](../README.md).
   Para mantenimiento de ramas y preparación de entregas, consultar [organización del repositorio](contexto-desarrollo.md#organizacion). La estructura académica exacta está pendiente de verificar; no aplicar exclusiones globales de Markdown.
4. [Conocimiento de integración extraído de Atlas](contexto-desarrollo.md#contexto): síntesis independiente, procedencia y límites del otro desarrollo. Para cambios de red continuar con [contratos](contexto-desarrollo.md#integraciones), [decisiones](contexto-desarrollo.md#continuidad) y [matriz de evidencia](contexto-desarrollo.md#evidencias).

## Contratos funcionales

- [Roles, redes asignadas e historial privado](chat-roles-y-persistencia.md).
- [Acceso Wi-Fi, diagnóstico y tickets](soporte-cliente.md).
- [Plan y estado del desarrollo](desarrollo-chat-roles.md).
- [Autenticación original](epica-001-autenticacion-roles.md).
- [Monitoreo](epica-002-monitoreo.md).
- [Frontend modular](../frontend/README.md).
- [Atención sin cuenta, QR y recuperación por contacto](atencion-invitados.md).
- [Gestión de SSID/AP con VLAN existentes: diseño pendiente](contexto-desarrollo.md#ssid).

## Referencias históricas y objetivos

[Arquitectura original](../../Arquitectura/LEEME_PRIMERO_ARQUITECTURA.md) conserva el diseño objetivo y sus diagramas transcritos. Los documentos de superpowers/specs y superpowers/plans son antecedentes de entregas anteriores; pueden mencionar contratos o instrucciones que ya cambiaron. Usar las guías vigentes y el código para decidir una modificación actual.

Actualizar la guía y el contrato correspondiente cuando cambien módulos, permisos, rutas, migraciones o arranque. No documentar UniFi, workers, aprovisionamiento CSV u otras funciones pendientes como implementadas.

### Carga CSV

Admin puede validar la [plantilla y contrato CSV](carga-csv.md), revisar filas y confirmar reservas locales. No crea SSIDs ni modifica infraestructura. Las cargas persisten por propietario y las vistas previas vencen. Producción requiere migración 005.
