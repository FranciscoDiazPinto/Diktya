import { createApi } from './api.mjs';
import { createDom } from './dom.mjs';
import * as format from './format.mjs';
import { createSession } from './session.mjs';
import { createChat } from './chat.mjs';
import { createMonitoring } from './monitoring.mjs';
import { createReservations } from './reservations.mjs';
import { createSupport } from './support.mjs';
import { createTickets } from './tickets.mjs';

export function createDashboard({document, window, localStorage, fetch, Option, crypto, FormData}) {
  const state = {user: null, session: 0};
  const api = createApi({fetch, localStorage, state});
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
  chat = createChat({document, Option, state, api, onConversationChanged: support.clearWifiAccess,
    onNetworksLoaded: support.setNetworks, renderAccessAction: support.renderAccessAction,
    renderTicketProposal: tickets.renderTicketProposal, renderReservationProposal: reservations.renderReservationProposal});
  const monitoring = createMonitoring({document, window, sessionState: state, api, format, ...dom,
    signOut: (message) => session.signOut(message)});
  const features = [monitoring, reservations, support, tickets, chat];
  session = createSession({document, state, api, FormData, ...dom,
    onAuthenticated(user) { for (const feature of features) feature.reset(); for (const feature of features) feature.configureUser(user); },
    onSignedOut() { for (const feature of features) feature.reset(); }});
  const sidebar = document.querySelector('.sidebar');
  document.querySelectorAll('.nav-item[href]').forEach((item) => item.addEventListener('click', () => {
    document.querySelector('.nav-item.active')?.classList.remove('active'); item.classList.add('active'); sidebar.classList.remove('open');
  }));
  document.querySelector('.mobile-menu').addEventListener('click', () => sidebar.classList.toggle('open'));
  return {session, api, chat, support, tickets, reservations, monitoring,
    start: session.validateSession};
}
