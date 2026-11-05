import { createAudit } from './audit.mjs';
import { createInventory } from './inventory.mjs';
import { createNotifications } from './notifications.mjs';
import { createNavigation } from './navigation.mjs';
import { createAccessPoints } from './access-points.mjs';
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
  let chat, session, support;
  const navigation = createNavigation({document,window,onViewChanged(previous,next){
    if(previous==='support-panel' && next!=='support-panel')support?.clearWifiAccess();
  }});
  const api = createApi({fetch, localStorage, state, onSessionExpired: () => session.expire()});
  const guest = createGuest({document, window, api, Option});
  const wifiRecipients = createWifiRecipients({document, Option, state, api});
  const dom = createDom({document, window});
  const chatMessages = document.querySelector('#chat-messages');
  const captureChat = () => chat.capture();
  const isChatCurrent = (context) => chat.isCurrent(context);
  support = createSupport({document, window, Option, state, api, chatMessages, ...dom,
    clockTime: format.clockTime, captureChat, isChatCurrent, onOpenSupport:()=>navigation.navigate('support-panel')});
  const tickets = createTickets({document, Option, crypto, state, api, chatMessages, ...dom,
    selectedNetworkId: support.selectedNetworkId, captureChat, isChatCurrent});
  const reservations = createReservations({document, state, api, chatMessages, ...dom});
  const csvImports = createCsvImports({document, Option, state, api, ...dom, onConfirmed: reservations.refresh});
  const ssidPlans = createSsidPlans({document, Option, state, api, ...dom, captureChat, isChatCurrent, chatMessages, onOpenPlans:()=>navigation.currentView==='overview' && navigation.navigate('provisioning')});
  chat = createChat({document, Option, state, api, onConversationChanged: support.clearWifiAccess,
    onNetworksLoaded: support.setNetworks, renderAccessAction: support.renderAccessAction,
    renderTicketProposal: tickets.renderTicketProposal, renderSsidProposal: ssidPlans.renderProposal, renderReservationProposal: reservations.renderReservationProposal});
  const monitoring = createMonitoring({document, window, sessionState: state, api, format, ...dom,
    signOut: (message) => session.signOut(message)});
  const accessPoints = createAccessPoints({document,window,Option,state,api,...dom,formatDuration:format.formatDuration});
  const inventory = createInventory({document, window, Option, state, api, ...dom});
  const notifications = createNotifications({document, window, state, api, ...dom, onOpenTicket:(id)=>{ navigation.navigate('tickets-panel'); document.querySelector('#ticket-'+Number(id))?.scrollIntoView?.(); }});
  const audit = createAudit({document, window, state, api});
  const features = [audit, inventory, notifications, accessPoints, monitoring, reservations, support, tickets, chat, csvImports, wifiRecipients, ssidPlans];
  session = createSession({document, window, state, api, FormData, ...dom,
    onAuthenticated(user) { guest.stop(); navigation.reset(); for (const feature of features) feature.reset(); for (const feature of features) feature.configureUser(user); navigation.configureUser(user); },
    onSignedOut({expired} = {}) { navigation.reset(); for (const feature of features) feature.reset(); if (expired) guest.stop(); else guest.start(); }});
  return {audit, navigation, inventory, notifications, accessPoints, ssidPlans, guest, wifiRecipients, session, api, chat, support, tickets, reservations, monitoring, csvImports,
    start() { guest.start(); return session.validateSession(); }};
}
