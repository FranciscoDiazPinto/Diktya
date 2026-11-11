"""Confirmación explícita en el dispositivo del destinatario; GET no consume enlaces."""
APPROVAL_HTML = '''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tu acceso Wi-Fi · Netbot</title><link rel="stylesheet" href="./approval.css"></head>
<body><main class="card"><header><a class="brand" href="#">NETBOT <span>ACCESO WI-FI</span></a><span class="badge">Expositores</span></header>
<div class="symbol" aria-hidden="true">⌁</div><p class="eyebrow">CONECTA CON TU EVENTO</p>
<h1 id="title">Tu conexión,<br>a un paso.</h1><p class="intro" id="intro">Confirma que solicitaste recuperar tu acceso. Tu código QR aparecerá aquí, en este dispositivo.</p>
<button id="approve" type="button">Confirmar y mostrar mi QR <span aria-hidden="true">→</span></button>
<p id="status" role="status" aria-live="polite"></p><div id="networks"></div>
<div class="privacy"><span aria-hidden="true">◷</span><p><strong>Tu acceso es personal</strong><br>El enlace vence en 5 minutos y solo se usa una vez. El QR se oculta después de 60 segundos. No compartas el enlace ni el QR.</p></div>
<footer>¿No solicitaste este correo? Puedes cerrar esta página.</footer></main>
<p class="signature">NETBOT · Asistencia para tu conexión</p><script src="./approval.js"></script></body></html>'''

APPROVAL_CSS = '''
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#172638;background:#f0f4f8;font-synthesis:none}
*{box-sizing:border-box}body{margin:0;min-height:100svh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 20px;background:radial-gradient(ellipse at 15% 0%,#dceee9,transparent 55%),radial-gradient(ellipse at 95% 95%,#dce6f5,transparent 55%)}
.card{width:100%;max-width:520px;padding:36px;background:#fff;border:1px solid #e0e7ed;border-radius:24px;box-shadow:0 20px 70px #233c5810}header{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:40px}.brand{text-decoration:none;color:#173c39;font-size:17px;font-weight:850;letter-spacing:2px}.brand span{display:block;font-size:9px;letter-spacing:1.7px;margin-top:4px;color:#627580}.badge{font-size:11px;background:#edf5f2;color:#35695c;border:1px solid #dcebe5;border-radius:30px;padding:7px 11px}.symbol{width:60px;height:60px;display:grid;place-items:center;border-radius:18px;background:#e9f5f0;color:#16735b;font-size:44px;margin-bottom:24px}.eyebrow{font-size:10px;letter-spacing:1.8px;font-weight:750;color:#497269;margin:0 0 12px}h1{font-size:40px;line-height:1.12;letter-spacing:-1.6px;margin:0 0 18px;font-weight:750}.intro{font-size:15px;line-height:1.7;color:#63717f;margin:0 0 27px}button{width:100%;border:0;border-radius:12px;padding:17px 18px;display:flex;align-items:center;justify-content:space-between;gap:12px;background:#176b55;color:#fff;font:inherit;font-size:14px;font-weight:650;cursor:pointer;transition:background .15s}button:hover{background:#105340}button:focus-visible,.brand:focus-visible{outline:3px solid #8cbfaa;outline-offset:4px}button:disabled{opacity:.6;cursor:default}button[hidden]{display:none}#status{font-size:14px;line-height:1.6;color:#426559;margin:18px 0}#status:empty{display:none}.error #status{color:#9e4134}.network{border:1px solid #dce9e2;border-radius:16px;text-align:center;padding:22px;margin:20px 0;background:#f9fcfa}.network h2{font-size:19px;overflow-wrap:anywhere;margin:0 0 4px}.network p{font-size:12px;color:#65776d;margin:0 0 14px}.network img{display:block;width:256px;max-width:100%;height:auto;margin:auto;border:10px solid #fff;border-radius:8px}.privacy{border-top:1px solid #e8edf0;margin-top:28px;padding-top:22px;display:flex;gap:12px;color:#77828c}.privacy>span{font-size:23px;color:#5c7a70}.privacy p{margin:0;font-size:12px;line-height:1.8}.privacy strong{font-weight:650;color:#465b60}footer{font-size:11px;color:#7c8790;line-height:1.6;margin-top:24px}.signature{font-size:10px;letter-spacing:1px;color:#72838c;text-align:center;margin:22px 0 0}@media(max-width:480px){body{padding:24px 16px}.card{padding:26px 22px;border-radius:20px}h1{font-size:35px}header{margin-bottom:30px}}
'''

APPROVAL_JS = '''const token = location.hash.slice(1);
history.replaceState(null, '', location.pathname);
const button = document.querySelector('#approve');
const status = document.querySelector('#status');
const networks = document.querySelector('#networks');
const title = document.querySelector('#title');
const intro = document.querySelector('#intro');
button.disabled = !token;
if (!token) {
  title.textContent = 'Necesitas un enlace nuevo';
  intro.textContent = 'Abre el enlace completo que recibiste por correo. Si ya lo utilizaste, solicita recuperar tu acceso nuevamente.';
  button.hidden = true;
}
let pending = false;
button.addEventListener('click', async () => {
  if (pending) return; pending = true; button.disabled = true;
  button.textContent = 'Verificando tu acceso…';
  status.textContent = 'Un momento, estamos preparando tu código QR.';
  try {
    const response = await fetch('./approve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({token})});
    if (!response.ok) throw new Error('El enlace venció, ya fue utilizado o no permite recuperar acceso. Solicita uno nuevo.');
    const result = await response.json();
    for (const network of result) {
      const card = document.createElement('section'); card.className = 'network';
      const label = document.createElement('h2'); label.textContent = network.ssid;
      const hint = document.createElement('p'); hint.textContent = 'Escanea con la cámara del dispositivo que deseas conectar.';
      const image = document.createElement('img'); image.alt = 'QR de acceso a ' + network.ssid; image.src = network.qr_data_url;
      card.append(label, hint, image); networks.append(card);
    }
    button.hidden = true;
    title.textContent = 'Tu acceso está listo';
    intro.textContent = 'Este código contiene el acceso a tu red Wi-Fi. Mantenlo privado.';
    status.textContent = 'El QR se ocultará automáticamente en 60 segundos.';
    setTimeout(() => {
      networks.replaceChildren(); title.textContent = 'Tu QR se ha ocultado';
      intro.textContent = 'Limpiamos el acceso de esta página para protegerlo.';
      status.textContent = 'Si necesitas verlo otra vez, solicita un nuevo enlace de recuperación.';
    }, 60000);
  } catch (error) {
    networks.replaceChildren(); document.body.classList.add('error'); button.hidden = true;
    title.textContent = 'No pudimos mostrar tu QR';
    intro.textContent = 'Vuelve al portal de recuperación para solicitar un nuevo enlace.';
    status.textContent = error instanceof TypeError ? 'No pudimos conectar con el servidor. Revisa tu conexión y solicita un nuevo enlace.' : error.message;
  }
});
window.addEventListener('pagehide', () => networks.replaceChildren());
'''
