"""Incorpora las fuentes corregidas al documento de diseño conservando su plantilla.

Uso: python Arquitectura/uml/actualizar_diseno.py --png-dir /tmp/netbot-figuras
Requiere python-docx. Generar primero SVG con corregir_diseno.py y PNG con
renderizar_diseno.cjs. No modifica DoD ni backlog. Revisión 04: no reaplica.
Con --previo transforma una copia de revisión 04 en diseño previo al desarrollo
(revisión 05). Usar las figuras de corregir_diseno.py --previo.
"""
import argparse
from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]

def put(par,text):
    if par.runs:
        par.runs[0].text=text
        for r in par.runs[1:]:r.text=''
    else:par.add_run(text)

def replace_picture(d, par, file, max_height=6.5):
    blip=par._p.xpath('.//a:blip')[0]
    rid=blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
    d.part.related_parts[rid]._blob=file.read_bytes()
    with Image.open(file) as im:
        w,h=im.size
    cx=int(Inches(6.7));cy=int(cx*h/w)
    if cy>Inches(max_height):
        cx=int(cx*Inches(max_height)/cy);cy=int(Inches(max_height))
    for ext in par._p.xpath('.//wp:extent | .//a:xfrm/a:ext'):
        ext.set('cx',str(cx));ext.set('cy',str(cy))

def design_only(path, png_dir):
    d=Document(path)
    pars=list(d.paragraphs)
    if 'Revisión 04' not in pars[2].text or pars[369].text != 'Correspondencia entre conceptos y persistencia':
        raise SystemExit('Se requiere una copia de revisión 04. No se sobrescriben revisiones posteriores.')
    updates={
      1:'Documento de Diseño de NetBot',
      2:'Proyecto NetBot\nRevisión 05\n12 de noviembre de 2026',
      3:'NetBot se diseña como un asistente de operación de red que combina monitoreo, solicitudes por chat y cambios controlados. Este documento define la solución propuesta antes de su implementación: arquitectura, permisos, datos, casos de uso y flujos de ejecución y recuperación conforme al Definition of Done.',
      5:'Equipo del proyecto',
      6:'Francisco Díaz · Programador y Product manager\nItamar Carrasco · Programador\nBastián Herrera · Programador',
      9:'Alcance y notación · Casos de uso generales · Clases de identidad y permisos · Especificación CU001 a CU019 · Secuencias S01 a S04 · Modelos E-R · Contratos y componentes · Persistencia y estados · Despliegue · Trazabilidad · Decisiones y validación',
      10:'Alcance y arquitectura propuesta',
      11:'La solución se organizará como un monolito modular: una interfaz web React, un backend Python con FastAPI y una base de datos PostgreSQL. El backend concentrará autorización, reglas de negocio e integración con servicios externos. React se contempla conforme al criterio de HU005 del DoD.',
      12:'UniFi Controller y OPNsense se consultarán mediante adaptadores con un contrato común de lectura, salud y errores. Las operaciones de escritura tendrán capacidades separadas y solo se utilizarán después de validar permisos, recursos, reserva y confirmación humana.',
      13:'El alcance funcional comprende las 19 historias HU001 a HU019: autenticación y roles; monitoreo y cobertura; chat, CSV y reservas; ejecución, verificación y auditoría; tickets y notificaciones; coordinación de agentes y configuración del proveedor LLM.',
      14:'La arquitectura separará presentación, servicios de aplicación, dominio y adaptadores. Los módulos expondrán contratos públicos y cada uno controlará su persistencia. Las tareas de monitoreo y tickets se ejecutarán independientemente de la apertura del dashboard, bajo los mismos controles de autorización.',
      15:'Notación UML: actores y elipses para casos de uso; clases con atributos, operaciones y multiplicidades; interfaces y sus realizaciones; componentes; nodos y artefactos de despliegue; secuencias con marco sd, líneas de vida y mensajes. Las actividades expresan acciones, decisiones, guardas y final. Referencia: OMG UML 2.5.1.',
      16:'Los participantes y operaciones representan responsabilidades propuestas del sistema. Cada HU se desarrolla en un caso de uso CU y una actividad ACT con el mismo número. S01 a S04 integran cambios por chat, CSV, incidentes y reinicios.',
      17:'Los límites de tiempo, permisos y reglas de recuperación se consideran requisitos de diseño. Las pruebas, revisión de pares, migraciones y evidencias de aceptación se planificarán durante la implementación de cada historia.',
      19:'Vista de requisitos con los actores definidos en el DoD. La asociación de un interesado con un proceso automático no implica que lo inicie manualmente. Los permisos se comprobarán en el servidor y por recurso. El detalle funcional se desarrolla en CU001 a CU019.',
      23:'Vista de requisitos con los actores definidos en el DoD. Los cambios se prepararán como propuestas y requerirán confirmación humana vinculada al actor y a los recursos. Las actividades y secuencias especifican autorización, reserva, ejecución y recuperación.',
      27:'Vista de requisitos de tickets, notificaciones y coordinación. Los ciclos automáticos detectarán y procesarán incidentes; los técnicos recibirán los avisos y realizarán el seguimiento. La configuración de proveedores quedará bajo administración autorizada.',
      30:'Clases de identidad y permisos',
      31:'CL01 propone las clases Usuario, Rol y Permiso, sus asociaciones y el ServicioAutorizacion. El servicio comprobará identidad, acción y ámbito de cada recurso en chat, dashboard y API. Una denegación se registrará en auditoría. ER01 detalla la persistencia conceptual de estas relaciones.',
      33:'CL01 Modelo de clases de identidad y autorización',
      157:'Especificación funcional del diseño',
      158:'Los casos de uso y modelos desarrollan las historias y criterios del Documento 04 Definition of Done. Sus precondiciones, resultados y excepciones orientarán la construcción y la validación de la solución.',
      159:'Se define un caso de uso CU por historia HU, con el mismo número. Algunas historias describen capacidades transversales o procesos automáticos: su actor representa al interesado externo y el disparador podrá ser interno. Las actividades detallan decisiones y las secuencias S01 a S04 integran los escenarios principales.',
      162:'Se utilizarán los roles Administrador de Red, Técnico de Red y Supervisor de Evento. La matriz de permisos será común a todos los canales. La autorización se resolverá en el backend por acción y por recurso; la interfaz mostrará únicamente las operaciones disponibles para el rol.',
      164:'Los cambios requerirán permiso, ámbito, reserva y confirmación explícita del resumen vigente. Se conservará el estado previo, se evitará duplicar la ejecución y se verificará el resultado. Los errores se registrarán sin secretos. Las reservas se distinguirán de la asignación efectiva y los estados desconocidos se mostrarán de forma explícita.',
      165:'Requisitos temporales: inventario con antigüedad máxima configurable de 60 s por defecto; dashboard con retraso máximo de 60 s; detección de caída AP en menos de 2 min; ticket en no más de 2 min desde la detección. Los intervalos de muestreo y procesamiento se configurarán para cumplir estos límites.',
      323:'HU007, HU009, HU010, HU012, HU013 y HU018. La confirmación se vinculará al actor, recursos y versión; la ejecución será idempotente. UniFi y OPNsense tendrán responsabilidades separadas. Se escribirá en cada fuente únicamente si la operación y el resumen confirmado lo requieren.',
      331:'Criterios: modificar solo los recursos confirmados; una confirmación repetida no duplicará la ejecución; se liberarán reservas canceladas o vencidas, se marcarán las consumidas y se conservarán las inciertas para conciliación. Un fallo del LLM detendrá la propuesta sin ejecutar cambios.',
      350:'ER01 a ER03 describen la persistencia conceptual del diseño. Cada multiplicidad corresponde al extremo rotulado: conversacion 1 — 0..* mensaje_chat; ticket 1 — 0..* notificacion. PK identifica clave primaria y FK referencia. Las relaciones opcionales admiten 0..1 padre; las restricciones de exclusividad se especifican por separado.',
      353:'ER01 Identidad y conversaciones. Un usuario podrá tener muchas conversaciones; cada conversación pertenecerá a un usuario y opcionalmente a una red. Cada mensaje pertenecerá a una conversación. Usuario_rol y rol_permiso representarán las asociaciones necesarias para resolver permisos.',
      361:'CP01 propone un monolito modular con interfaz React y backend Python/FastAPI. Los componentes representan responsabilidades lógicas dentro de la aplicación. Se comunicarán mediante contratos públicos y eventos correlacionados; los adaptadores aislarán las APIs externas.',
      363:'Composición iniciará y detendrá las tareas; monitoreo publicará observaciones normalizadas; tickets consumirá incidentes; cambios autorizará, reservará, confirmará, ejecutará y verificará; auditoría conservará los eventos relevantes. Los agentes tendrán permisos explícitos y no podrán omitir la confirmación humana.',
      364:'Contratos propuestos',
      366:'Se proponen contratos comunes para satisfacer el DoD. La flecha discontinua con triángulo vacío indica realización. LLMProvider abstraerá el proveedor de lenguaje; los adaptadores OpenRouter y Claude normalizarán respuestas y errores. El puerto de lectura de infraestructura abstraerá UniFi y OPNsense.',
      369:'Persistencia y restricciones del diseño',
      370:'Las entidades conceptuales del modelo E-R se implementarán mediante un esquema relacional. La tabla resume responsabilidades y restricciones que deberán conservarse al definir las tablas, índices y migraciones.',
      372:'Las clases representan responsabilidades de diseño para los flujos integrales: autorizar, reservar, confirmar, ejecutar, verificar, compensar, auditar y notificar. Las operaciones orientarán los contratos de los servicios de aplicación.',
      375:'Las transiciones de tickets se validarán en el servicio y conservarán eventos. El cierre exigirá motivo. El vencimiento de atención generará un nuevo aviso y elevará la criticidad según configuración. Los estados y las transiciones válidas se documentarán antes de construir la persistencia y la interfaz.',
      377:'DP01 propone una topología de despliegue con interfaz web, servidor de aplicación y PostgreSQL. UniFi, OPNsense, el proveedor LLM y SMTP serán servicios externos. Se utilizará HTTPS y configuración protegida para las credenciales de integración.',
      379:'Se prevén contenedores Docker para la aplicación y la base de datos. La configuración del entorno establecerá conexiones, canales de notificación, tiempos de espera y reintentos. Los secretos permanecerán en el servidor y fuera de los diagramas, del contexto LLM y de los registros de auditoría.',
      381:'La matriz enlaza cada historia con su caso de uso, actividad y modelos de diseño. S01 a S04 integran los flujos que requieren interacción entre componentes. ER01 a ER03 describen datos; CL01, identidad y permisos; las clases de servicios e interfaces y CP01 complementan la arquitectura.',
      382:'El DoD de HU011 remite a S01. Se conserva esa referencia y se añade S04 para especificar el reinicio con confirmación, timeout y recuperación. ACT011 complementa el flujo. S01 seguirá describiendo el cambio de VLAN por chat.',
      383:'Decisiones y criterios de validación',
      384:'Las decisiones siguientes fijan la base de diseño y las aclaraciones que deberán acordarse antes de implementar las operaciones afectadas. Cualquier ajuste a los criterios del DoD se registrará y validará con las partes responsables.',
      385:'Validación prevista',
      386:'Cada historia deberá cumplir sus criterios de negocio y técnicos: pruebas por criterio, documentación de contratos, migraciones cuando correspondan y revisión de pares mediante PR. El DoD admite mocks en integración. Las pruebas temporales y de recuperación se diseñarán con evidencias adecuadas al comportamiento que se quiera comprobar.',
      387:'La validación abarcará permisos en todos los canales, concurrencia, idempotencia, exclusión de secretos, recuperación y tratamiento de errores. Los resultados y evidencias de ejecución se registrarán en los documentos de seguimiento del proyecto.',
      389:'Documento_01_Product_Vision.docx. Documento_02_Product_Backlog.docx. Documento_04_Definition_of_Done.docx, revisión 01. OMG Unified Modeling Language 2.5.1, https://www.omg.org/spec/UML/2.5.1/.'
    }
    for idx,value in updates.items():put(pars[idx],value)
    pars[10].paragraph_format.page_break_before=False
    pars[364].paragraph_format.page_break_before=True
    for idx,name in [(32,'CL01_identidad_permisos'),(362,'CP01_componentes'),(378,'DP01_despliegue')]:
        replace_picture(d,pars[idx],png_dir/(name+'.png'))
    # Retirar el inventario de clases físicas y las 19 secuencias del código observado.
    # Los CU/ACT y las secuencias integrales contienen la especificación funcional.
    for par in pars[34:157]:
        par._p.getparent().remove(par._p)
    history=d.tables[0]
    put(history.rows[2].cells[1].paragraphs[0],'Equipo NetBot. Revisión de las vistas UML y organización por historias de usuario.')
    put(history.rows[3].cells[1].paragraphs[0],'Alineación con DoD: 19 casos de uso y actividades, secuencias integrales, modelo E-R y trazabilidad.')
    put(history.rows[4].cells[1].paragraphs[0],'Corrección de multiplicidades, separación de fuentes, tratamiento de fallos CSV y secuencia de reinicio.')
    row=history.add_row()
    put(row.cells[0].paragraphs[0],'12/11/2026 · 05')
    put(row.cells[1].paragraphs[0],'Reorganización como diseño previo al desarrollo: arquitectura propuesta, modelos conceptuales, flujos y validación prevista.')
    contract_rows=[
      ('Contrato de diseño','Responsabilidad'),
      ('LLMProvider','Interpretar solicitudes con contexto autorizado y sin secretos; ofrecer adaptadores OpenRouter y Claude con respuestas y errores normalizados.'),
      ('Cliente común de infraestructura','Consultar salud, inventario y fecha del dato; normalizar errores mediante una interfaz común. Mantener capacidades específicas de UniFi y OPNsense separadas de la escritura.'),
      ('Eventos entre agentes','Incluir event_id, correlation_id, agent_id, occurred_at, network_id, resource_id, tipo y resultado sin secretos. Versionar el esquema y deduplicar por event_id.'),
      ('Ejecución de cambios','Recibir propuesta versionada, actor, ámbito, reserva, confirmación, clave idempotente y estado previo protegido; entregar resultado verificado o fallo con recuperación y escalamiento.')]
    data_rows=[
      ('Entidades de diseño','Responsabilidad y restricción'),
      ('Usuario, rol y auditoría','Conservar identidad, estado activo y asociaciones de rol. La auditoría identificará actor, acción, recurso, fecha y resultado; solo permitirá inserciones desde la aplicación.'),
      ('Permiso y rol_permiso','Relacionar acciones permitidas con roles. Aplicar la misma autorización por recurso en chat, dashboard y API; denegar y auditar solicitudes fuera de permiso.'),
      ('Conversación y mensaje_chat','Cada conversación pertenecerá a un usuario y podrá referenciar una red. Conservar mensajes propios sin credenciales ni datos de terceros.'),
      ('Carga_csv y carga_csv_fila','Cada carga conservará filas, validaciones y selección confirmada. Registrar el resultado individual sin contraseñas en logs ni auditoría.'),
      ('VLAN y reserva_cambio','Relacionar la reserva con actor, ámbito y recurso. Garantizar una sola reserva activa por recurso mediante restricción o bloqueo transaccional; liberar al vencer o cancelar.'),
      ('SSID y cambio_ejecucion','Relacionar cambios con la reserva y los recursos confirmados. Guardar versión, estado previo protegido y resultado; soportar idempotencia, verificación y compensación.'),
      ('Alerta, plano y dispositivo','Deduplicar condiciones activas. Cada dispositivo podrá tener como máximo una ubicación; los equipos sin ubicación se listarán como sin ubicar.'),
      ('Ticket, seguimiento y notificación','Mantener un único ticket abierto por incidente, su historial y motivo de cierre. Cada notificación se asociará al ticket y al usuario destinatario.'),
      ('Configuración LLM','Seleccionar proveedor y secretos mediante configuración de entorno protegida, sin incorporar credenciales a tablas de negocio, mensajes o auditoría.')]
    decision_rows=[
      ('Tema','Decisión o aclaración prevista'),
      ('Interfaz web','Se propone React conforme al criterio técnico de HU005. La interfaz consumirá los contratos del backend y mostrará acciones según permisos.'),
      ('Roles','Usar Administrador de Red, Técnico de Red y Supervisor de Evento. Documentar y probar una matriz común para todos los canales.'),
      ('Permisos','Modelar usuario_rol y rol_permiso en ER01 y CL01. Aplicar permisos por acción y por recurso desde el servicio de autorización.'),
      ('CSV y confirmación','Validar archivo y filas antes de la vista previa. Identificar sobrescrituras y procesar únicamente la selección confirmada con recursos reservados.'),
      ('Cambios y reinicio','Separar cambio de configuración y reinicio. Ambos requerirán confirmación, exclusión concurrente y verificación; S01 y S04 especifican sus diferencias.'),
      ('Recuperación','Acordar el alcance de compensación de lotes CSV y el tratamiento de reinicios irreversibles. Conservar estados inciertos y escalar fallos de recuperación.'),
      ('Contratos de red','Utilizar un contrato común para salud, lectura y errores, con capacidades específicas por fuente. Mantener la escritura separada de la lectura y del LLM.'),
      ('Proveedores LLM','Prever adaptadores OpenRouter y Claude seleccionables por entorno. Definir normalización de respuestas, disponibilidad, errores y pruebas de contrato.'),
      ('Aceptación','Planificar pruebas y evidencias por criterio del DoD, documentación OpenAPI, migraciones y revisión de pares. El seguimiento registrará sus resultados.')]
    for table,rows in [(d.tables[2],contract_rows),(d.tables[3],data_rows),(d.tables[5],decision_rows)]:
        for row,values in zip(table.rows,rows):
            for cell,value in zip(row.cells,values):put(cell.paragraphs[0],value)
            row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        table.rows[0]._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
    trace=d.tables[4]
    models={1:'ER01; CL01; casos de uso 1',2:'ER01; CL01; casos de uso 1',3:'ER01; CL01; casos de uso 1',4:'ER02; interfaces; CP01',5:'ER02; casos de uso 1; CP01',6:'ER03; casos de uso 1',7:'ER01/ER02; clases de servicios; casos de uso 2',8:'ER02; clases de servicios',9:'ER02; clases de servicios',10:'ER02; clases de servicios; CP01',11:'ER02/ER03; casos de uso 2',12:'ER02/ER03; clases de servicios',13:'ER01/ER02; auditoría',14:'ER03; clases de servicios',15:'ER03; CP01',16:'ER03; casos de uso 3',17:'ER03; interfaces; CP01',18:'ER01/ER02/ER03; clases de servicios; CP01',19:'Interfaces; CP01; DP01'}
    flows={7:'ACT007; S01',8:'ACT008; S02',9:'ACT009; S01/S02',10:'ACT010; S01',11:'ACT011; S01 (DoD)/S04',12:'ACT012; S01/S02/S04',14:'ACT014; S03',15:'ACT015; S03',16:'ACT016; S03',17:'ACT017; S03',18:'ACT018; S01/S03'}
    for c,t in zip(trace.rows[0].cells,['Historia','Caso de uso','Flujo de referencia','Modelos']):put(c.paragraphs[0],t)
    for i in range(1,20):
        values=[f'HU{i:03}',f'CU{i:03}',flows.get(i,f'ACT{i:03}'),models[i]]
        for c,t in zip(trace.rows[i].cells,values):put(c.paragraphs[0],t)
    # No conservar medios huérfanos con diagramas de implementación retirados.
    used={b.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed') for b in d.element.xpath('.//a:blip')}
    for rid,rel in list(d.part.rels.items()):
        if rel.reltype.endswith('/image') and rid not in used:d.part.drop_rel(rid)
    d.save(path)
    print('Documento de diseño previo al desarrollo:',path)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docx',type=Path)
    parser.add_argument('--png-dir',type=Path,required=True)
    parser.add_argument('--previo',action='store_true',help='Convertir revisión 04 en diseño previo al desarrollo, revisión 05.')
    args=parser.parse_args()
    path=args.docx or next((ROOT/'Fase 2/Evidencias Proyecto').glob('Documento_05*.docx'))
    if args.previo:
        design_only(path,args.png_dir)
        return
    d=Document(path)
    if 'Revisión 04' in d.paragraphs[2].text:raise SystemExit('Documento ya actualizado a revisión 04; conservar ediciones posteriores.')
    updates={
      2:'Proyecto NetBot\nRevisión 04\n12 de noviembre de 2026',
      3:'Diseño UML de NetBot contrastado con el Definition of Done de referencia. Actualiza el corte técnico al 12/11/2026 y conserva separados los casos de uso, actividades y secuencias del diseño objetivo. Documentar un comportamiento no acredita su implementación ni el cierre de una historia.',
      9:'Alcance y notación · Vistas del corte técnico · Secuencias HU001 a HU019 · Diseño objetivo · Actores y permisos · Casos de uso y actividades CU001 a CU019 · Secuencias S01 a S04 · Modelos E-R · Contratos y componentes · Trazabilidad y diferencias',
      11:'Este documento describe el software integrado al 12/11/2026. El sistema es un monolito modular con frontend estático ES y backend Python; no utiliza React. Se separan implementación disponible, validación pendiente y diseño objetivo.',
      12:'Corte técnico al 12/11/2026: dev e311e57 y main b917996 tienen el mismo árbol versionado antes de esta revisión documental. En la revisión del repositorio se aprobaron 495 pruebas backend y 81 frontend. No se reejecutan por editar este documento. Los resultados simulados no acreditan operación física ni aprobación de pares.',
      13:'Historias con cierre integral acreditado: 0. En revisión funcional: HU001, HU002, HU003, HU014 y HU016 (23 puntos). Parciales: HU004–HU010, HU012, HU013, HU015 y HU017–HU019 (93 puntos). Pendiente: HU011 (5 puntos). Total: 19 historias y 121 puntos. Los puntos parciales no son avance ganado.',
      16:'Cada HU dispone de una secuencia de corte técnico. Los participantes representan módulos, clases o actores del proyecto. Los nombres con paréntesis identifican funciones verificadas. CU001 a CU019 y S01 a S04 especifican el objetivo; sus responsabilidades conceptuales no se presentan como componentes ya operativos.',
      17:'HU010 ya tiene API de propuesta/confirmación y servicio interno de ejecución con pruebas simuladas; aún no está conectado al chat, al panel ni al CLI que procesa planes de creación. HU011 sigue sin operación de reinicio. HU008/HU012 tienen verificación limitada, sin rollback integral. El objetivo se desarrolla en CU010, CU011 y S01 a S04.',
      38:'Modelo de datos de cambios del corte técnico',
      39:'CL01 muestra WifiScope, SsidPlan, SsidVlanChangePlan y WifiWriteLease de app/changes/models.py. CsvImport y VlanReservation conservan el flujo de reservas locales. Resultados y filas se guardan como JSON. HU010 requiere migraciones 013 y 014; no existe un cambio genérico con rollback implementado.',
      41:'CL01 Modelo físico de planes y exclusión compartida',
      59:'Topología local: navegador, aplicación y SQLite o PostgreSQL según configuración. UniFi, OPNsense y LLM son integraciones externas; el diagrama no acredita laboratorio físico. SMTP Brevo y recuperación Wi-Fi de demostración se validaron con el usuario el 11/11; producción y correo de tickets requieren validación propia.',
      73:'En revisión funcional. Contrastar matriz de permisos en chat/panel/API, integrar el flujo HU010, completar HU011 y documentar revisión de pares.',
      108:'Parcial. Propuesta y confirmación HTTP; servicio interno con estado previo, reautorización, exclusión durable y verificación de configuración. Falta integración al flujo del usuario y al CLI, rollback y laboratorio.',
      110:'HU010 Secuencia del servicio implementado al 12 de noviembre',
      111:'Participantes: Actor API, SsidPlanService, WifiInventory y UniFiSsidWriter. Evidencia: app/changes/router.py, ssid_service.py, ssid_executor.py, models.py; tests/test_ssid_vlan_change.py; migraciones 013 y 014. execute_vlan_change no se expone por HTTP ni al LLM; el CLI actual solo consume SsidPlan.',
      118:'Parcial. Verificación de creación y HU010 con estados inciertos. Compensación, conciliación operativa y escalamiento de rollback fallido pendientes.',
      123:'Parcial. Consulta unificada y eventos HU010 de inicio, resultado y estado incierto. Faltan todos los hitos de ejecución/rollback, consulta propia del técnico y aceptación de interfaz.',
      133:'Parcial. SMTP y recepción de recuperación Wi-Fi validados con el usuario; no equivalen a correo de tickets. Validar tickets reales, reintentos, lectura, hora y contraste.',
      158:'Esta sección especifica el objetivo a partir de Documento 04 Definition of Done, revisión 01 del 04/10/2026. Las clases y contratos conceptuales complementan el corte técnico actualizado; no afirman que existan nuevas tablas, métodos o workers. Las diferencias abiertas requieren aceptación explícita.',
      160:'Las actividades muestran inicio, acciones, decisiones con guardas, fusiones y final. En las secuencias cada fragmento alt separa sus alternativas; loop representa repetición y break interrumpe la interacción de procesamiento ante fallo. Las continuaciones tienen precondiciones explícitas y no repiten la ejecución. S01/S02 separan fuentes y responsabilidades.',
      249:'Disparador y flujo principal: Validar permiso y recurso; preparar impacto y confirmar; reautorizar antes de adquirir exclusión y activar mantenimiento; ejecutar y comprobar retorno.',
      250:'Resultado esperado: Equipo recuperado o incidente abierto. Cerrar mantenimiento y liberar la exclusión, o transferirla explícitamente a conciliación cuando el estado siga incierto.',
      251:'Alternativas y excepciones: Rechazo o falta de permiso no adquieren exclusión. Técnico no reinicia gateway/firewall. Timeout: alerta y ticket. El reinicio no se deshace; se trata mediante recuperación y escalamiento.',
      319:'Diseño objetivo. HU007, HU009, HU010, HU012, HU013 y HU018. Confirmación vinculada al actor, recursos y versión; ejecución idempotente. UniFi y OPNsense tienen responsabilidades separadas. Escribir en OPNsense solo corresponde si la operación y el resumen lo requieren; HU010 actual únicamente reasocia redes existentes en UniFi.',
      322:'Continuación de S01_1 solo para el plan confirmado y autorizado. Aplicar exclusivamente el resumen vigente; comprobar cada fuente pertinente. Una falla conduce a S01_3 conservando exclusión y evidencia.',
      325:'Recuperación de S01_2 y notificación final. Conciliar antes de repetir escrituras ambiguas. La restauración verificada permite liberar recursos; un estado incierto conserva exclusión y genera incidente crítico.',
      327:'Criterios: recursos exactamente confirmados; confirmaciones repetidas no duplican ejecución; liberar reservas canceladas o vencidas; pasar a asignadas las consumidas y conservar las inciertas. Fallo del LLM detiene la propuesta sin ejecutar. El diseño objetivo no habilita escrituras actualmente pendientes.',
      332:'Procesamiento S02_2 solo con selección y versión confirmadas, autorización y reservas vigentes. El fragmento break detiene nuevas filas en el primer fallo y deriva a la recuperación S02_3; no continúa con la siguiente fila.',
      335:'S02_3 cierra el lote sin repetir su procesamiento: concilia y compensa el alcance fallido, registra reservas y resultados por fila, y devuelve un resumen seguro.',
      337:'Política propuesta para acordar: detener nuevas filas ante fallo; compensar la fila afectada y cambios aún no consolidados, conservar filas previas verificadas y declarar su resultado. Liberar reservas no aplicadas/restauradas; conservar exclusión de recursos inciertos y escalar. El rollback de todas las filas anteriores y las sobrescrituras requieren acuerdo explícito; esta propuesta no modifica el DoD.',
      342:'Seguimiento S03_2 independiente del nacimiento de nuevos incidentes: reintento de correo, atención manual, escalamiento por plazo y resolución por recuperación. Una falla de agente se registra y deriva sin detener los demás.',
      346:'ER01 a ER03 son modelos conceptuales del DoD. Cada multiplicidad pertenece al extremo rotulado: conversacion 1 — 0..* mensaje_chat; ticket 1 — 0..* notificacion. PK identifica clave primaria y FK referencia. Las opcionales admiten 0..1 padre; las restricciones activas se expresan por separado. No son migraciones físicas.',
      349:'ER01 Identidad y conversaciones. Un usuario puede tener muchas conversaciones; cada conversación pertenece a un usuario y opcionalmente a una red. Cada mensaje pertenece a una conversación. Usuario_rol y rol_permiso son asociaciones conceptuales; los permisos físicos siguen definidos en código.',
      352:'ER02 Inventario, cambios y cargas. Cada ejecución pertenece a una reserva; una reserva puede no ejecutarse. Reserva_cambio identifica VLAN o dispositivo según operación, con exclusividad de reservas activas por ámbito. Filas del CSV pertenecen a una carga y pueden referenciar una reserva. Los enlaces de red, actor y auditoría son explícitos.',
      355:'ER03 Alertas, tickets y cobertura. Cada notificación pertenece a un ticket y a un usuario; cada evento a un ticket y opcionalmente a un actor. Una alerta puede no tener dispositivo y un ticket puede no proceder de alerta. Máximo un ticket abierto por clave de incidente; ubicación opcional y única por dispositivo.',
      366:'Correspondencia contrastada con el corte técnico del 12/11. El diseño objetivo usa conceptos de negocio; la tabla identifica modelos físicos, límites y migraciones sin afirmar equivalencias funcionales completas.',
      377:'La matriz identifica figuras concretas para cada HU: CU/ACT numerados; secuencias HU del corte técnico; S01–S04 del objetivo; ER01–ER03; CL01 de cambios físicos; clases de integración y de servicios objetivo. Cobertura documental no acredita pruebas, aprobación de pares ni aceptación.',
      378:'El DoD de HU011 remite a S01, aunque trata reinicios. Se conserva S01 como referencia de origen y se añade S04 Reinicio con confirmación, timeout y tratamiento de falla; ACT011 la complementa. La secuencia HU011 del corte técnico conserva el rechazo actual, sin presentar reinicios implementados.',
      382:'Para cierre: PR y aprobación de otro integrante; versión, pruebas por criterio, migración/configuración y demostración de reglas de negocio. El DoD permite mocks en integración; no exige hardware real para todos los criterios. Las garantías temporales necesitan evidencia apropiada y una simulación no acredita operación física.',
      383:'Estado al 12/11: cinco HU en revisión funcional, trece parciales y HU011 pendiente; sin cierres integrales acreditados. Esta revisión corrige diseño y trazabilidad; no cierra historias ni acredita implementaciones objetivo.',
      385:'Documento_04_Definition_of_Done.docx, revisión 01, 04/10/2026. Documento_02_Product_Backlog.docx, revisión 05, 12/11/2026. README y código dev e311e57 / main b917996. Fuentes corregidas: Arquitectura/uml/corregir_diseno.py, secuencias_corregidas.json y diseno_actualizado/*.svg. OMG UML 2.5.1: https://www.omg.org/spec/UML/2.5.1/.'
    }
    for idx,t in updates.items():put(d.paragraphs[idx],t)
    # Replace image bytes and update drawing extents to preserve the new ratio.
    replacements={40:'CL01_cambios_actual',109:'HU010_actual',252:'ACT011_corregida',320:'S01_1',323:'S01_2',326:'S01_3',330:'S02_1',333:'S02_2',336:'S02_3',340:'S03_1',343:'S03_2',348:'ER01_identidad',351:'ER02_cambios',354:'ER03_tickets'}
    for idx,name in replacements.items():
        par=d.paragraphs[idx];blip=par._p.xpath('.//a:blip')[0];rid=blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
        file=args.png_dir/(name+'.png');d.part.related_parts[rid]._blob=file.read_bytes()
        w,h=Image.open(file).size
        cx=int(Inches(6.7));cy=int(cx*h/w)
        maxh=Inches(6.65) if idx in [109,320,323,326,330,333,336,340,343] else Inches(6.5)
        if cy>maxh:cx=int(cx*maxh/cy);cy=int(maxh)
        for e in par._p.xpath('.//wp:extent | .//a:xfrm/a:ext'):e.set('cx',str(cx));e.set('cy',str(cy))
    # New objective restart sequence; preserve the existing current-state HU011.
    anchor=d.paragraphs[254]
    head=anchor.insert_paragraph_before('S04 Reinicio de dispositivo con confirmación');head.style='Heading 1';head.paragraph_format.page_break_before=True
    par=anchor.insert_paragraph_before('Diseño objetivo de HU011/HU012/HU017. La ejecución requiere confirmación vigente y exclusión por dispositivo. Un timeout exige recuperación o incidente; nunca se promete deshacer un reinicio.');par.paragraph_format.space_after=Pt(8)
    par=anchor.insert_paragraph_before();par.alignment=1
    shape=par.add_run().add_picture(str(args.png_dir/'S04_reinicio.png'),width=Inches(6.7))
    if shape.height>Inches(6.45):shape.width=int(shape.width*Inches(6.45)/shape.height);shape.height=Inches(6.45)
    anchor.insert_paragraph_before('S04 Secuencia objetivo de reinicio y recuperación')
    anchor.paragraph_format.page_break_before=True
    # History and mapping retain original records and business criteria.
    row=d.tables[0].add_row();put(row.cells[0].paragraphs[0],'12/11/2026 · 04');put(row.cells[1].paragraphs[0],'Corrección E-R, fuentes separadas, salida de CSV ante fallo, reinicio objetivo y corte técnico al 12/11. Fuentes SVG y trazabilidad por figura; sin cierre de HU.')
    phys=d.tables[3]
    put(phys.rows[6].cells[1].paragraphs[0],'MonitoredSsid, SsidPlan y SsidVlanChangePlan; WifiWriteLease compartido. HU010 guarda redes previa/destino y resultado. Falta integración operativa y rollback. Migraciones 013 y 014; ver CL01.')
    figures={1:'ER01; casos de uso 1; HU001',2:'ER01; casos de uso 1; HU002',3:'ER01; casos de uso 1; clases identidad; HU003',4:'ER02; clases integración; componentes; HU004',5:'ER02; casos de uso 1; componentes; HU005',6:'ER03; casos de uso 1; HU006',7:'ER01/ER02; clases objetivo; casos de uso 2; S01',8:'ER02; S02',9:'ER02; clases objetivo; S01/S02',10:'ER02; CL01; clases objetivo; componentes; S01',11:'ER02/ER03; casos de uso 2; S01 y S04',12:'ER02/ER03; clases objetivo; S01/S02/S04',13:'ER01/ER02; HU013',14:'ER03; clases tickets; S03',15:'ER03; componentes; S03',16:'ER03; casos de uso 3; S03',17:'ER03; clases integración; componentes; S03',18:'ER01/ER02/ER03; clases objetivo; componentes; S01/S03',19:'Interfaces y componentes objetivo; HU019; entorno sin tablas'}
    for i,t in figures.items():put(d.tables[4].rows[i].cells[3].paragraphs[0],t)
    put(d.tables[4].rows[11].cells[2].paragraphs[0],'S01 (referencia DoD), S04 y ACT011')
    diffs=d.tables[5]
    put(diffs.rows[4].cells[1].paragraphs[0],'CSV local y planes SSID con ejecutor de creación disponibles. HU010 tiene servicio separado sin conexión a chat/panel/CLI. S01/S02 representan el flujo objetivo; no acreditan despliegue ni rollback.')
    put(diffs.rows[5].cells[1].paragraphs[0],'HU010 parcial al 12/11; HU011 pendiente. HU010_actual y CL01 documentan implementación; CU010/CU011, S01 y S04 documentan el objetivo.')
    for row in d.tables[4].rows:
        trpr=row._tr.get_or_add_trPr();trpr.append(OxmlElement('w:cantSplit'))
        for c in row.cells:
            for par in c.paragraphs:
                par.paragraph_format.space_before=Pt(0);par.paragraph_format.space_after=Pt(0)
                par.paragraph_format.line_spacing=1.0
                for r in par.runs:r.font.size=Pt(10)
    d.tables[4].rows[0]._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
    d.save(path)
    print('Documento corregido:',path)
if __name__=='__main__':main()
