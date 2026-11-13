"""Orquestación de agentes: contratos de eventos, trazas y ciclo de vida.

Los agentes siguen siendo servicios de sus dominios (monitoreo, tickets, cambios). Este
módulo los coordina dentro del monolito: registra quién actuó en cada evento, aísla sus
fallas y enruta incidentes hacia tickets sin acoplar los dominios entre sí.
"""
