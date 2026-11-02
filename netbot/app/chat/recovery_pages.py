"""Confirmación explícita en el dispositivo del destinatario; GET no consume enlaces."""
APPROVAL_HTML = '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Confirmar acceso Wi-Fi</title></head><body><h1>Acceso Wi-Fi de expositor</h1><p>Confirma únicamente si solicitaste recuperar tu acceso. El QR se mostrará en este dispositivo.</p><button id="approve" type="button">Confirmar y mostrar mi QR</button><p id="status" role="status"></p><div id="networks"></div><p>El QR se borra de esta página al cabo de un minuto. No compartas el enlace ni el QR.</p><script src="./approval.js"></script></body></html>'''
APPROVAL_JS = '''const token = location.hash.slice(1);
history.replaceState(null, '', location.pathname);
const button = document.querySelector('#approve');
const status = document.querySelector('#status');
const networks = document.querySelector('#networks');
button.disabled = !token;
let pending = false;
button.addEventListener('click', async () => {
  if (pending) return; pending = true; button.disabled = true;
  try {
    const response = await fetch('./approve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({token})});
    if (!response.ok) throw new Error('El enlace venció, ya fue utilizado o no permite recuperar acceso. Solicita uno nuevo.');
    const result = await response.json();
    for (const network of result) {
      const label = document.createElement('p'); label.textContent = network.ssid;
      const image = document.createElement('img'); image.alt = 'QR de acceso Wi-Fi'; image.src = network.qr_data_url;
      networks.append(label, image);
    }
    status.textContent = 'Escanea tu QR o utiliza otro dispositivo para conectarte.';
    setTimeout(() => { networks.replaceChildren(); status.textContent = 'El QR se limpió. Solicita otro enlace si lo necesitas.'; }, 60000);
  } catch (error) { status.textContent = error.message; }
});
window.addEventListener('pagehide', () => networks.replaceChildren());
'''
