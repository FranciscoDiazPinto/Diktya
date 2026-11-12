"""Fuentes de las figuras corregidas en Documento 05, revisión 04.

Genera SVG editables en diseno_actualizado/. Renderizar a PNG con Sharp y usar
actualizar_diseno.py para incorporarlos al DOCX. No modifica código operativo.
Las cardinalidades pertenecen al extremo rotulado, según UML.
"""
from pathlib import Path
from html import escape
import argparse, json, textwrap
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'diseno_actualizado'
INK = '#20333f'
class Drawing:
    def __init__(self, width=1200, height=1000):
        self.w,self.h=width,height
        self.p=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="white"/>', '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" fill="#20333f"/></marker></defs>']
    def line(self, points, dash=False, arrow=False):
        pts=' '.join(f'{x},{y}' for x,y in points)
        self.p.append(f'<polyline points="{pts}" fill="none" stroke="{INK}" stroke-width="2"'+(' stroke-dasharray="7 5"' if dash else '')+(' marker-end="url(#arrow)"' if arrow else '')+'/>')
    def text(self,x,y,t,size=23,anchor='middle',bold=False,wrap=0):
        ls=[]
        for s in str(t).split('\n'):ls.extend(textwrap.wrap(s,wrap,break_long_words=False) if wrap else [s])
        for i,s in enumerate(ls):self.p.append(f'<text x="{x}" y="{y+i*(size+6)}" font-family="Arial,DejaVu Sans,sans-serif" font-size="{size}" text-anchor="{anchor}" fill="{INK}"'+(' font-weight="bold"' if bold else '')+'>'+escape(s)+'</text>')
    def rect(self,x,y,w,h,fill='#f3f6f8',round=0):
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{round}" fill="{fill}" stroke="{INK}" stroke-width="2"/>')
    def save(self,name):
        OUT.mkdir(exist_ok=True);(OUT/(name+'.svg')).write_text('\n'.join(self.p+['</svg>']))

def model(name, nodes, links, size=(1200,1050), notes=()):
    s=Drawing(size[0]+80,size[1]+80);s.p.append('<g transform="translate(40 40)">')
    # Draw edges first so they do not overwrite entity labels.
    for a,pa,b,pb,ma,mb in links:
        x,y,w,h,*_=nodes[a];u,v,z,k,*_=nodes[b]
        ports=lambda x,y,w,h: {'t':(x+w/2,y),'b':(x+w/2,y+h),'l':(x,y+h/2),'r':(x+w,y+h/2)}
        p=ports(x,y,w,h)[pa];q=ports(u,v,z,k)[pb]
        if pa in 'lr' and pb in 'lr':
            mx=(p[0]+q[0])/2;points=[p,(mx,p[1]),(mx,q[1]),q]
        elif pa in 'tb' and pb in 'tb':
            my=(p[1]+q[1])/2;points=[p,(p[0],my),(q[0],my),q]
        else:points=[p,(q[0],p[1]),q]
        custom={
          ('ER01_identidad','u','c'):[p,(15,p[1]),(15,570),(q[0],570),q],
          ('ER01_identidad','r','ur'):[p,(p[0],240),(590,240),(590,q[1]),q],
          ('ER01_identidad','r','rp'):[p,(800,p[1]),(800,250),(q[0],250),q],
          ('ER01_identidad','p','rp'):[p,(p[0],240),(1090,240),(1090,q[1]),q],
          ('CL01_identidad_permisos','r','ur'):[p,(p[0],240),(590,240),(590,q[1]),q],
          ('CL01_identidad_permisos','r','rp'):[p,(800,p[1]),(800,250),(q[0],250),q],
          ('CL01_identidad_permisos','p','rp'):[p,(p[0],240),(1090,240),(1090,q[1]),q],
          ('ER02_cambios','u','r'):[p,(800,p[1]),(800,260),(q[0],260),q],
          ('ER02_cambios','u','a'):[p,(1185,p[1]),(1185,q[1]),q],
          ('ER03_tickets','u','n'):[p,(p[0],900),(1185,900),(1185,q[1]),q],
        }
        s.line(custom.get((name,a,b),points))
        offsets={'t':(20,-13),'b':(20,27),'l':(-26,-12),'r':(26,-12)}
        for pos,port,lab in [(p,pa,ma),(q,pb,mb)]:
            dx,dy=offsets[port];s.text(pos[0]+dx,pos[1]+dy,lab,22)
    for x,y,w,h,title,attrs in nodes.values():
        s.rect(x,y,w,h);s.text(x+w/2,y+32,title,28,bold=True);s.line([(x,y+49),(x+w,y+49)])
        for i,a in enumerate(attrs):s.text(x+12,y+80+i*29,a.replace(' opcional','?').replace('contenido_sin_secretos','contenido sin secretos'),26,'start')
    for x,y,t in notes:s.text(x,y,t,20,wrap=90)
    s.p.append('</g>');s.save(name)

def models(include_observed=True):
    model('ER01_identidad',{
      'u':(35,35,315,165,'usuario',['PK id_usuario','correo','activo']),
      'r':(440,35,300,140,'rol',['PK id_rol','nombre']),
      'p':(850,35,315,140,'permiso',['PK id_permiso','accion']),
      'ur':(240,325,320,140,'usuario_rol',['PK/FK id_usuario','PK/FK id_rol']),
      'rp':(740,325,320,140,'rol_permiso',['PK/FK id_rol','PK/FK id_permiso']),
      'red':(35,680,280,140,'red',['PK id_red','nombre']),
      'c':(450,650,320,195,'conversacion',['PK id_conversacion','FK id_usuario','FK id_red opcional']),
      'm':(890,650,280,195,'mensaje_chat',['PK id_mensaje','FK id_conversacion','contenido_sin_secretos'])},[
      ('u','b','ur','t','1','0..*'),('r','b','ur','r','1','0..*'),('r','r','rp','t','1','0..*'),('p','b','rp','r','1','0..*'),
      ('u','l','c','t','1','0..*'),('red','r','c','l','0..1','0..*'),('c','r','m','l','1','0..*')],size=(1200,950))
    model('ER02_cambios',{
      'red':(30,25,290,135,'red',['PK id_red','nombre']),
      'u':(875,25,290,135,'usuario',['PK id_usuario','correo']),
      'v':(30,280,290,165,'vlan',['PK id_vlan','FK id_red','tag']),
      'dev':(440,25,300,165,'dispositivo',['PK id_dispositivo','FK id_red','estado']),
      'r':(440,315,340,225,'reserva_cambio',['PK id_reserva','FK id_usuario','FK id_vlan opcional','FK id_dispositivo opcional','estado y vencimiento']),
      'csv':(875,310,290,165,'carga_csv',['PK id_carga','FK id_usuario','estado']),
      'ssid':(30,660,290,195,'ssid',['PK id_ssid','FK id_red','FK id_vlan opcional']),
      'e':(440,750,340,225,'cambio_ejecucion',['PK id_cambio','FK id_reserva','estado_previo_protegido','confirmacion y version','resultado']),
      'fila':(875,660,290,195,'carga_csv_fila',['PK id_fila','FK id_carga','FK id_reserva opcional','estado sin secretos']),
      'a':(875,1100,290,225,'auditoria',['PK id_evento','FK id_usuario opcional','FK id_cambio opcional','agente y correlacion','accion resultado fecha'])},[
      ('red','b','v','t','1','0..*'),('red','r','dev','l','1','0..*'),('v','b','ssid','t','0..1','0..*'),
      ('u','b','csv','t','1','0..*'),('u','l','r','t','1','0..*'),('v','r','r','l','0..1','0..*'),
      ('dev','b','r','t','0..1','0..*'),('r','b','e','t','1','0..1'),('r','r','fila','l','0..1','0..*'),
      ('csv','b','fila','t','1','0..*'),('e','r','a','l','0..1','0..*'),('u','r','a','r','0..1','0..*'),
      ('red','l','ssid','l','1','0..*')],size=(1200,1390),notes=[(600,1370,'Reserva: VLAN o dispositivo según operación; exclusividad solo entre reservas activas del mismo ámbito.')])
    model('ER03_tickets',{
      'd':(35,35,320,165,'dispositivo',['PK id_dispositivo','FK id_red','estado']),
      'p':(860,35,300,140,'plano_cobertura',['PK id_plano','nombre e imagen']),
      'a':(35,340,320,195,'alerta',['PK id_alerta','FK id_dispositivo opcional','clave_incidente','estado y severidad']),
      'loc':(860,340,300,165,'ubicacion_dispositivo',['PK/FK id_dispositivo','FK id_plano','coordenadas']),
      't':(440,650,340,195,'ticket',['PK id_ticket','FK id_alerta opcional','clave_incidente','estado y criticidad']),
      'u':(35,690,300,140,'usuario',['PK id_usuario','correo y activo']),
      'e':(35,1040,340,195,'ticket_seguimiento',['PK id_evento','FK id_ticket','FK id_usuario opcional','estado motivo fecha']),
      'n':(860,1040,300,195,'notificacion',['PK id_notificacion','FK id_ticket','FK id_usuario','canal estado intentos'])},[
      ('d','b','a','t','0..1','0..*'),('d','r','loc','l','1','0..1'),('p','b','loc','t','1','0..*'),
      ('a','r','t','t','0..1','0..*'),('t','b','e','r','1','0..*'),('t','r','n','t','1','0..*'),
      ('u','b','e','t','0..1','0..*'),('u','r','n','r','1','0..*')],size=(1200,1340),notes=[(600,1305,'Máximo un ticket abierto por clave de incidente; cada dispositivo tiene como máximo una ubicación.')])
    if not include_observed:
        return
    model('CL01_cambios_actual',{
      'w':(430,25,330,140,'WifiScope',['id: int','site_id: str']),
      's':(35,310,360,225,'SsidPlan',['id: str','scope_id: int','owner_id: int','status: str','execution_results: JSON']),
      'v':(760,310,400,310,'SsidVlanChangePlan',['id: str','scope_id: int','broadcast_id: str','current_network_id: str','target_network_id: str','revision: str','status: str','execution_results: JSON']),
      'l':(430,760,370,195,'WifiWriteLease',['resource_key: str [PK]','plan_id: str [0..1]','vlan_plan_id: str [0..1]','{exclusión compartida}'])},[
      ('w','l','s','t','1','0..*'),('w','r','v','t','1','0..*'),('s','b','l','l','0..1','0..*'),('v','b','l','r','0..1','0..*')],notes=[(600,1020,'CsvImport y VlanReservation conservan el flujo local. Modelos físicos: app/changes/models.py.')])

def sequence(name, people, rows):
    # Rows: message [from,to,text,reply], frame [op,guard], else [guard], end [], note [text].
    h=155+len(rows)*89;s=Drawing(1500,h);s.rect(10,10,1480,h-20,'white');s.text(30,42,'sd '+name,25,'start',True)
    xs=[110+i*1280/(len(people)-1) for i in range(len(people))]
    for x,p in zip(xs,people):
      s.rect(x-100,68,200,64);s.text(x,92,p,22,wrap=15);s.line([(x,132),(x,h-25)],True)
    stack=[];y=180
    for row in rows:
      kind=row[0]
      if kind=='msg':
        _,a,b,t,*ret=row;x,z=xs[a],xs[b];reply=bool(ret and ret[0])
        if a==b:s.line([(x,y+15),(x+55,y+15),(x+55,y+40),(x,y+40)],reply,True)
        else:s.line([(x,y+35),(z,y+35)],reply,True)
        # Full-width text lane: avoids unreadably small text over adjacent lifelines.
        s.text(750,y-12,t,28,wrap=80)
      elif kind=='frame':
        depth=len(stack);stack.append((y-30,depth));s.text(38+depth*14,y-5,row[1]+' ['+row[2]+']',22,'start')
      elif kind=='else':
        depth=stack[-1][1];s.line([(25+depth*14,y-25),(1470-depth*14,y-25)],True);s.text(38+depth*14,y,row[1],22,'start')
      elif kind=='end':
        top,depth=stack.pop();s.rect(23+depth*14,top,1450-depth*28,y-top+15,'none');s.text(38+depth*14,y,'fin '+row[1] if len(row)>1 else 'fin',19,'start')
      elif kind=='note':
        s.rect(60,y-28,1380,65,'#fff9e8');s.text(750,y,row[1],22,wrap=110)
      y+=89
    assert not stack,name
    s.save(name)

def sequences(include_observed=True):
    data=json.loads((ROOT/'secuencias_corregidas.json').read_text())
    for name,item in data.items():
        if include_observed or name != 'HU010_actual':
            sequence(name,item['participants'],item['rows'])

def prospective_views():
    """Vistas conceptuales independientes del código y del estado del repositorio."""
    model('CL01_identidad_permisos',{
      'u':(35,35,315,195,'Usuario',['identificador','correo','activo','+ iniciarSesion()']),
      'r':(440,35,300,140,'Rol',['identificador','nombre']),
      'p':(850,35,315,140,'Permiso',['identificador','accion']),
      'ur':(240,325,320,140,'UsuarioRol',['usuario','rol']),
      'rp':(740,325,320,140,'RolPermiso',['rol','permiso']),
      's':(350,650,520,225,'ServicioAutorizacion',['+ validarIdentidad()','+ verificarPermiso()','+ verificarAmbito()','+ registrarDenegacion()'])},[
      ('u','b','ur','t','1','0..*'),('r','b','ur','r','1','0..*'),
      ('r','r','rp','t','1','0..*'),('p','b','rp','r','1','0..*')],size=(1200,980),
      notes=[(600,940,'El servicio consulta las asociaciones y aplica permisos por acción y recurso en chat, dashboard y API.')])
    s=Drawing(1200,1000)
    nodes={
      'ui':(400,45,400,110,'Interfaz web React'),
      'auth':(30,290,330,110,'Identidad y permisos'),
      'chat':(435,290,330,110,'Chat y propuestas'),
      'mon':(840,290,330,110,'Monitoreo y cobertura'),
      'chg':(30,565,330,110,'Reservas y cambios'),
      'tick':(435,565,330,110,'Tickets y avisos'),
      'adap':(840,565,330,110,'Adaptadores externos'),
      'audit':(400,845,400,100,'Auditoría')}
    for a,b in [('ui','auth'),('ui','chat'),('ui','mon'),('chat','chg'),('mon','tick'),('chg','adap'),('mon','adap'),('tick','adap')]:
        x,y,w,h,_=nodes[a];u,v,z,k,_=nodes[b]
        if (a,b)==('chg','adap'):
            points=[(x+w/2,y+h),(x+w/2,720),(u+z/2,720),(u+z/2,v+k)]
        elif y==v:
            points=[(x+w,y+h/2),(u,v+k/2)]
        else:
            points=[(x+w/2,y+h),(u+z/2,v)]
        s.line(points,True,True)
    for x,y,w,h,title in nodes.values():
        s.rect(x,y,w,h);s.text(x+w/2,y+61,title,27,bold=True)
        s.rect(x-8,y+12,17,10);s.rect(x-8,y+33,17,10)
    s.text(600,775,'Auditoría recibe eventos de identidad, chat, cambios y tickets.',25)
    s.save('CP01_componentes')
    s=Drawing(1200,1020)
    def node(x,y,w,h,kind,title,artifact):
        s.rect(x,y,w,h);s.text(x+w/2,y+29,kind,21)
        s.text(x+w/2,y+62,title,26,bold=True)
        s.text(x+w/2,y+100,artifact,23,wrap=27)
    node(360,30,480,155,'«device»','Equipo de usuario','«artifact» Interfaz React')
    node(360,295,480,180,'«executionEnvironment»','Servidor de aplicación','«artifact» Backend Python / FastAPI')
    node(35,650,350,150,'«executionEnvironment»','PostgreSQL','«artifact» Datos persistentes')
    node(440,650,350,150,'«executionEnvironment»','Servicios de red','UniFi Controller / OPNsense')
    node(865,650,300,150,'«executionEnvironment»','Servicios auxiliares','Proveedor LLM / SMTP')
    s.line([(600,185),(600,295)]);s.text(650,245,'HTTPS',23,'start')
    for end,label in [(210,'SQL'),(615,'API HTTPS'),(1015,'API HTTPS / correo TLS')]:
        s.line([(600,475),(end,650)]);s.text(end,610,label,21)
    s.text(600,895,'Contenedores Docker para aplicación y base de datos.',25)
    s.text(600,945,'Los secretos se suministran mediante configuración protegida del servidor.',23)
    s.save('DP01_despliegue')

def activity_restart():
    s=Drawing(1000,1100)
    def box(y,t):s.rect(240,y,520,72,round=15);s.text(500,y+29,t,23,wrap=42)
    s.p.append('<circle cx="500" cy="25" r="10" fill="#20333f"/>')
    box(65,'Validar identidad, permiso y recurso');box(190,'Preparar resumen y pedir confirmación')
    for y,z in [(35,65),(137,190),(262,310)]:s.line([(500,y),(500,z)],arrow=True)
    s.p.append('<polygon points="500,310 760,365 500,420 240,365" fill="#f3f6f8" stroke="#20333f" stroke-width="2"/>');s.text(500,360,'¿Confirmación y permiso vigentes?',22)
    s.line([(500,420),(500,475)],arrow=True);s.text(545,453,'[sí]',21)
    box(475,'Adquirir exclusión y activar mantenimiento');box(600,'Enviar reinicio; esperar retorno con timeout');box(725,'Registrar recuperación o emitir alerta/ticket');box(850,'Cerrar mantenimiento; liberar o transferir bloqueo')
    for y,z in [(547,600),(672,725),(797,850)]:s.line([(500,y),(500,z)],arrow=True)
    s.rect(5,455,205,160,round=12);s.text(108,486,'Rechazar y auditar; no adquirir exclusión ni activar mantenimiento',20,wrap=18)
    s.line([(240,365),(108,365),(108,455)],arrow=True);s.text(150,350,'[no]',21)
    s.line([(108,615),(108,1000),(500,1000)]);s.line([(500,922),(500,1000)])
    s.p.append('<circle cx="500" cy="1035" r="16" fill="white" stroke="#20333f" stroke-width="2"/><circle cx="500" cy="1035" r="10" fill="#20333f"/>');s.line([(500,1000),(500,1018)],arrow=True)
    s.save('ACT011_corregida')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previo',action='store_true',help='Generar solo las figuras del diseño previo al desarrollo.')
    args=parser.parse_args()
    if args.previo:
        OUT=ROOT/'diseno_previo'
    models(include_observed=not args.previo);sequences(include_observed=not args.previo);activity_restart()
    if args.previo:
        prospective_views()
    print('Fuentes SVG generadas en',OUT)
