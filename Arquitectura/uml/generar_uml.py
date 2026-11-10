"""Genera SVG UML editables sin servicios externos ni dependencias adicionales.

Uso: python Arquitectura/uml/generar_uml.py
Notación: OMG UML 2.5.1 https://www.omg.org/spec/UML/2.5.1/
Los mensajes describen responsabilidades; no son contratos nuevos de código.
"""
import json, math, textwrap
from pathlib import Path
from html import escape
ROOT=Path(__file__).resolve().parent
INK='#17283b'; BLUE='#eaf0f5'
class SVG:
 def __init__(self,w=1000,h=900):
  self.w=w;self.h=h;self.parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',f'<rect width="{w}" height="{h}" fill="white"/>','<defs><marker id="call" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#17283b"/></marker><marker id="reply" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10" fill="none" stroke="#17283b"/></marker><marker id="general" markerWidth="14" markerHeight="14" refX="13" refY="7" orient="auto"><path d="M0,0 L14,7 L0,14 Z" fill="white" stroke="#17283b"/></marker></defs>']
 def rect(self,x,y,w,h,fill='white',dash=False):self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{INK}" stroke-width="2"'+(' stroke-dasharray="8 6"' if dash else '')+'/>')
 def line(self,x,y,a,b,dash=False,arrow=None):self.parts.append(f'<path d="M{x},{y} L{a},{b}" fill="none" stroke="{INK}" stroke-width="2"'+(' stroke-dasharray="8 6"' if dash else '')+(f' marker-end="url(#{arrow})"' if arrow else '')+'/>')
 def txt(self,x,y,s,size=23,anchor='middle',bold=False):
  for j,line in enumerate(str(s).split('\n')):self.parts.append(f'<text x="{x}" y="{y+j*(size+7)}" font-family="DejaVu Sans,Arial,sans-serif" font-size="{size}" text-anchor="{anchor}" fill="{INK}" stroke="white" stroke-width="3" paint-order="stroke"'+(' font-weight="bold"' if bold else '')+'>'+escape(line)+'</text>')
 def actor(self,x,y,name):
  self.parts.append(f'<circle cx="{x}" cy="{y}" r="13" stroke="{INK}" stroke-width="2" fill="white"/>');self.line(x,y+13,x,y+53);self.line(x-25,y+30,x+25,y+30);self.line(x,y+53,x-23,y+78);self.line(x,y+53,x+23,y+78);self.txt(x,y+107,name,21)
 def save(self,name):(ROOT/(name+'.svg')).write_text('\n'.join(self.parts+['</svg>']))
def wrap(s,n=26):return '\n'.join(textwrap.wrap(s,n,break_long_words=True,break_on_hyphens=False))
def seq(item):
 msgs=item['messages'];h=260+len(msgs)*90
 s=SVG(1000,h);s.rect(8,8,984,h-16);s.rect(8,8,205,43,BLUE);s.txt(25,37,'sd '+item['id'],24,'start',True)
 xs=[115,365,615,865]
 for i,name in enumerate(item['participants']):
  s.rect(xs[i]-111,76,222,91,BLUE);s.txt(xs[i],105,wrap(name,18),22,bold=True);s.line(xs[i],167,xs[i],h-45,True)
 for j,m in enumerate(msgs):
  a,b,label,*ret=m;y=235+j*90;reply=bool(ret and ret[0]);x,z=xs[a],xs[b]
  if a==b:
   s.parts.append(f'<path d="M{x},{y} h65 v34 h-65" stroke="{INK}" stroke-width="2" fill="none" marker-end="url(#call)"/>');s.txt(min(790,x+10),y-43,wrap(label,28),22)
  else:
   s.line(x,y,z,y,reply,'reply' if reply else 'call');s.txt((x+z)/2,y-36,wrap(label,max(23,int(abs(z-x)/12))),22)
 s.save(item['id'])
def cls(s,x,y,name,attrs,w=280):
 h=68+len(attrs)*32;s.rect(x,y,w,h);s.txt(x+w/2,y+31,name,22,bold=True);s.line(x,y+48,x+w,y+48)
 for i,a in enumerate(attrs):s.txt(x+12,y+79+32*i,a,21,'start')
 return (x,y,w,h)
def assoc(s,a,b,ma='1',mb='0..*'):
 x,y,w,h=a;u,v,z,k=b
 if abs(y-v)>150:
  sx=x+w*(.75 if x<u else .25) if abs(x-u)>100 else x+w/2
  ex=u+z*(.25 if x<u else .75) if abs(x-u)>100 else u+z/2
  if y<v:start=(sx,y+h);end=(ex,v)
  else:start=(sx,y);end=(ex,v+k)
  s.line(*start,*end)
  s.txt(start[0]+25,start[1]+(25 if y<v else -12),ma,20)
  s.txt(end[0]+25,end[1]+(-12 if y<v else 25),mb,20)
 else:
  start=(x+w,y+60) if x<u else (x,y+60)
  end=(u,v+60) if x<u else (u+z,v+60)
  s.line(*start,*end)
  s.txt(start[0]+(30 if x<u else -30),start[1]-12,ma,20)
  s.txt(end[0]+(-30 if x<u else 30),end[1]-12,mb,20)

def model(name,boxes,edges):
 s=SVG(1000,900);s.txt(30,40,'class '+name,25,'start',True);b={}
 for key,x,y,label,attrs in boxes:b[key]=cls(s,x,y,label,attrs)
 for a,c,ma,mb in edges:assoc(s,b[a],b[c],ma,mb)
 s.save(name)
def structural():
 model('modelo_identidad',[
 ('u',60,95,'User',['id: int','email: str','is_active: bool']),('r',650,95,'Role',['id: int','name: str']),('t',60,420,'RefreshToken',['id: int','user_id: int','expires_at: datetime']),('a',650,420,'AuthAuditEvent',['id: int','actor_id: int [0..1]','target_id: int [0..1]','action: str','outcome: str'])],[('u','r','0..*','0..*'),('u','t','1','0..*'),('u','a','0..1','0..*')])
 model('modelo_conversacion',[
 ('u',55,95,'User',['id: int']),('n',655,95,'Network',['id: int','name: str']),('c',55,360,'Conversation',['id: str','user_id: int','network_id: int [0..1]','version: int']),('m',655,360,'ChatMessage',['id: int','conversation_id: str','role: str','content: str'])],[('u','c','1','0..*'),('c','m','1','0..*')])
 model('modelo_cambios',[
 ('v',50,95,'VlanReservation',['id: int','tag: int','status: str']),('c',655,95,'CsvImport',['id: str','status: str']),('s',50,390,'WifiScope',['id: int','site_id: str']),('p',655,390,'SsidPlan',['id: str','scope_id: int','status: str'])],[('s','p','1','0..*')])
 model('modelo_tickets',[
 ('a',50,95,'MonitoringAlert',['id: int','device_id: int [0..1]']),('t',655,95,'Ticket',['id: int','alert_id: int [0..1]','status: str','criticality: str']),('e',50,440,'TicketEvent',['id: int','ticket_id: int','note: str']),('n',655,440,'Notification',['id: int','ticket_id: int','user_id: int','status: str'])],[('a','t','0..1','0..*'),('t','e','1','0..*'),('t','n','1','0..*')])
 model('modelo_inventario',[
 ('d',50,95,'MonitoredDevice',['id: int','state: str']),('a',655,95,'MonitoringAlert',['id: int','device_id: int [0..1]']),('p',50,440,'CoveragePlan',['id: int','name: str']),('l',655,440,'DevicePlacement',['id: int','plan_id: int','device_id: int'])],[('d','a','0..1','0..*'),('p','l','1','0..*')])
 s=SVG(1000,900);s.txt(35,40,'class Contratos de integración',25,'start',True)
 for x,name in [(50,'ChatProvider'),(650,'InfrastructureSource')]:
  s.rect(x,90,280,160);s.txt(x+140,120,'«interface»',21);s.txt(x+140,152,name,22,bold=True);s.line(x,170,x+280,170);s.txt(x+140,208,'+ complete()' if x==50 else '+ collect_inventory()',21)
 cls(s,50,400,'OpenRouterProvider',['+ complete()']);cls(s,650,400,'UnifiMonitoringProvider',['+ collect_inventory()'])
 s.line(190,400,190,250,True,'general');s.line(790,400,790,250,True,'general');s.txt(500,730,'Realización de interfaces del proyecto',23)
 s.save('contratos')
 s=SVG(1000,990);s.txt(25,40,'cmp Componentes del monolito modular',25,'start',True)
 names=['frontend/modules','auth','chat','networks','changes','monitoring','tickets','audit'];coords=[(365,70),(40,280),(365,280),(690,280),(40,550),(365,550),(690,550),(365,800)]
 for (x,y),name in zip(coords,names):
  s.rect(x,y,270,100,BLUE);s.txt(x+135,y+59,name,25,bold=True);s.rect(x+238,y+12,20,29);s.rect(x+231,y+16,13,7);s.rect(x+231,y+30,13,7)
 # Vista de dependencias principales; las restantes se detallan en el texto.
 for a,c in [(0,1),(0,2),(0,3),(2,4),(2,5),(2,6)]:
  x,y=coords[a];u,v=coords[c];s.line(x+135,y+100,u+135,v,True,'reply')
 s.txt(500,765,'audit consulta proyecciones públicas de auth, networks, changes y tickets',19)
 s.save('componentes')
 # Use case views have separate actors to avoid a single illegible all-HU diagram.
 items=json.loads((ROOT/'historias.json').read_text())
 for group,ids in enumerate([range(1,7),range(7,14),range(14,20)],1):
  s=SVG(1000,1050);s.rect(300,35,675,970);s.txt(635,73,'NetBot',27,bold=True);s.actor(115,450,'Usuario autorizado')
  for j,n in enumerate(ids):
   y=145+j*120;s.parts.append(f'<ellipse cx="635" cy="{y}" rx="300" ry="48" stroke="{INK}" stroke-width="2" fill="{BLUE}"/>');s.txt(635,y-8,wrap(f'HU{n:03} '+items[n-1]['title'],39),22);s.line(145,490,335,y)
  s.save(f'casos_uso_{group}')
 s=SVG(1000,920);s.txt(30,40,'deployment Entorno de desarrollo',25,'start',True)
 def node(x,y,w,h,label,artifact):
  s.rect(x,y,w,h,BLUE);s.parts.append(f'<path d="M{x},{y} l18,-16 h{w} v{h} l-18,16 M{x+w},{y} l18,-16" fill="none" stroke="{INK}" stroke-width="2"/>');s.txt(x+w/2,y+35,label,23,bold=True);s.rect(x+18,y+67,w-36,h-85);s.txt(x+w/2,y+99,artifact,22)
 node(45,100,360,235,'«device» Equipo usuario','«artifact»\nfrontend estático ES')
 node(595,100,360,235,'«device» Equipo servidor','«artifact»\nnetbot/app')
 node(595,485,360,235,'«executionEnvironment»','«artifact»\nSQLite de desarrollo')
 s.line(405,215,595,215);s.txt(500,196,'HTTP local',21);s.line(775,335,775,485);s.txt(795,410,'SQL',21,'start');s.txt(500,815,'Topología local observada, no despliegue productivo validado',23)
 s.save('despliegue')
if __name__=='__main__':
 for item in json.loads((ROOT/'historias.json').read_text()):seq(item)
 structural()
