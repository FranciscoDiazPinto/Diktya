import { createSsidPlans } from './ssid-plans.mjs';
import { createGuest } from './guest.mjs';
import { createWifiRecipients } from './wifi-recipients.mjs';
import { createApi } from './api.mjs';
import { createDom } from './dom.mjs';
import * as format from './format.mjs';
import { createSession } from './session.mjs';
import { createChat } from './chat.mjs';
import { createMonitoring } from './monitoring.mjs';
import { createReservations } from './reservations.mjs';
import { createSupport } from './support.mjs';
import { createTickets } from './tickets.mjs';
import { createCsvImports } from './csv-imports.mjs';

export function createDashboard({document, window, localStorage, fetch, Option, crypto, FormData}) {
  const state = {user: null, session: 0};
  const api = createApi({fetch, localStorage, state});
  const guest = createGuest({document, window, api, Option});
  const wifiRecipients = createWifiRecipients({document, Option, state, api});
  const dom = createDom({document, window});
  const chatMessages = document.querySelector('#chat-messages');
  let chat, session;
  const captureChat = () => chat.capture();
  const isChatCurrent = (context) => chat.isCurrent(context);
  const support = createSupport({document, window, Option, state, api, chatMessages, ...dom,
    clockTime: format.clockTime, captureChat, isChatCurrent});
  const tickets = createTickets({document, Option, crypto, state, api, chatMessages, ...dom,
    selectedNetworkId: support.selectedNetworkId, captureChat, isChatCurrent});
  const reservations = createReservations({document, state, api, chatMessages, ...dom});
  const csvImports = createCsvImports({document, Option, state, api, ...dom, onConfirmed: reservations.refresh});
  const ssidPlans = createSsidPlans({document, Option, state, api, ...dom, captureChat, isChatCurrent, chatMessages});
  chat = createChat({document, Option, state, api, onConversationChanged: support.clearWifiAccess,
    onNetworksLoaded: support.setNetworks, renderAccessAction: support.renderAccessAction,
    renderTicketProposal: tickets.renderTicketProposal, renderSsidProposal: ssidPlans.renderProposal, renderReservationProposal: reservations.renderReservationProposal});
  const monitoring = createMonitoring({document, window, sessionState: state, api, format, ...dom,
    signOut: (message) => session.signOut(message)});
  const features = [monitoring, reservations, support, tickets, chat, csvImports, wifiRecipients, ssidPlans];
  session = createSession({document, state, api, FormData, ...dom,
    onAuthenticated(user) { guest.stop(); for (const feature of features) feature.reset(); for (const feature of features) feature.configureUser(user); },
    onSignedOut() { for (const feature of features) feature.reset(); guest.start(); }});
  const sidebar = document.querySelector('.sidebar');
  document.querySelectorAll('.nav-item[href]').forEach((item) => item.addEventListener('click', () => {
    document.querySelector('.nav-item.active')?.classList.remove('active'); item.classList.add('active'); sidebar.classList.remove('open');
  }));
  document.querySelector('.mobile-menu').addEventListener('click', () => sidebar.classList.toggle('open'));
  return {ssidPlans, guest, wifiRecipients, session, api, chat, support, tickets, reservations, monitoring, csvImports,
    start() { guest.start(); return session.validateSession(); }};
}
