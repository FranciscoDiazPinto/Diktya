import { createAudit } from "../../modules/audit.mjs";
import { createInventory } from "../../modules/inventory.mjs";
import { createNotifications } from "../../modules/notifications.mjs";
import { createAccessPoints } from "../../modules/access-points.mjs";
import { createSsidPlans } from "../../modules/ssid-plans.mjs";
import { createWifiRecipients } from "../../modules/wifi-recipients.mjs";
import { createDom } from "../../modules/dom.mjs";
import * as format from "../../modules/format.mjs";
import { createChat } from "../../modules/chat.mjs";
import { createReservations } from "../../modules/reservations.mjs";
import { createSupport } from "../../modules/support.mjs";
import { createTickets } from "../../modules/tickets.mjs";
import { createCsvImports } from "../../modules/csv-imports.mjs";
import { createChangePlans } from "../../modules/change-plans.mjs";
import { createUsers } from "../../modules/users.mjs";
import { createAccount } from "../../modules/account.mjs";
import { createSystemStatus } from "../../modules/system-status.mjs";

import { createControllerScope } from "./controller-scope.mjs";

export function mountFeatures(root, runtime, navigate) {
  const scope = createControllerScope(root, runtime);
  const { document, window, state, api, Option, crypto } = scope;
  const dom = { ...createDom({ document, window }), showToast: runtime.notify };
  const wifiRecipients = createWifiRecipients({ document, Option, state, api });
  let chat, support;
  const navigation = {
    navigate,
    get currentView() {
      return runtime.currentView;
    },
  };
  const chatMessages = document.querySelector("#chat-messages");
  const captureChat = () => chat.capture();
  const isChatCurrent = (context) => chat.isCurrent(context);
  support = createSupport({
    document,
    window,
    Option,
    state,
    api,
    chatMessages,
    ...dom,
    clockTime: format.clockTime,
    captureChat,
    isChatCurrent,
    onOpenSupport: () => navigation.navigate("support-panel"),
  });
  const tickets = createTickets({
    document,
    Option,
    crypto,
    state,
    api,
    chatMessages,
    ...dom,
    selectedNetworkId: support.selectedNetworkId,
    captureChat,
    isChatCurrent,
  });
  const reservations = createReservations({
    document,
    state,
    api,
    chatMessages,
    ...dom,
  });
  const csvImports = createCsvImports({
    document,
    Option,
    state,
    api,
    ...dom,
    onConfirmed: reservations.refresh,
  });
  const ssidPlans = createSsidPlans({
    document,
    Option,
    state,
    api,
    ...dom,
    captureChat,
    isChatCurrent,
    chatMessages,
    onOpenPlans: () =>
      navigation.currentView === "overview" &&
      navigation.navigate("provisioning"),
  });
  const openProvisioning = () =>
    navigation.currentView === "overview" &&
    navigation.navigate("provisioning");
  const changePlans = createChangePlans({
    document,
    Option,
    state,
    api,
    ...dom,
    captureChat,
    isChatCurrent,
    chatMessages,
    onOpenPlans: openProvisioning,
  });
  chat = createChat({
    document,
    Option,
    state,
    api,
    onConversationChanged: support.clearWifiAccess,
    onNetworksLoaded: support.setNetworks,
    renderAccessAction: support.renderAccessAction,
    renderTicketProposal: tickets.renderTicketProposal,
    renderSsidProposal: ssidPlans.renderProposal,
    renderVlanProposal: changePlans.renderVlanProposal,
    renderRestartProposal: changePlans.renderRestartProposal,
    renderReservationProposal: reservations.renderReservationProposal,
  });
  const accessPoints = createAccessPoints({
    document,
    window,
    Option,
    state,
    api,
    ...dom,
    formatDuration: format.formatDuration,
  });
  const inventory = createInventory({
    document,
    window,
    Option,
    state,
    api,
    ...dom,
  });
  const notifications = createNotifications({
    document,
    window,
    state,
    api,
    ...dom,
    onOpenTicket: (id) => {
      navigation.navigate("tickets-panel");
      window.setTimeout(
        () =>
          document.querySelector("#ticket-" + Number(id))?.scrollIntoView?.(),
        0,
      );
    },
  });
  const audit = createAudit({ document, window, state, api });
  const users = createUsers({ document, state, api, ...dom });
  const systemStatus = createSystemStatus({
    document,
    window,
    state,
    api,
    ...dom,
  });
  const account = createAccount({
    document,
    state,
    api,
    onPasswordChanged: () =>
      runtime.signOut("Contraseña actualizada. Inicia sesión con la nueva."),
  });
  const features = [
    audit,
    inventory,
    notifications,
    accessPoints,
    reservations,
    support,
    tickets,
    chat,
    csvImports,
    wifiRecipients,
    ssidPlans,
    changePlans,
    users,
    systemStatus,
    account,
  ];

  for (const feature of features) feature.reset();
  for (const feature of features) feature.configureUser(state.user);
  scope.finishMount();
  return {
    support,
    dispose() {
      scope.dispose();
      for (const feature of features) feature.reset();
    },
  };
}
