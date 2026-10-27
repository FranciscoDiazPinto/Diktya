import { canReserveVlans } from '../chat-reservations.mjs';

export function createChat({ document, Option, state, api, onConversationChanged, onNetworksLoaded, renderReservationProposal, renderAccessAction, renderTicketProposal }) {
  const $ = (selector) => document.querySelector(selector);
  const { authedRequest } = api;
  const chatForm = document.querySelector('#chat-form');
  const chatInput = document.querySelector('#chat-message');
  const chatMessages = document.querySelector('#chat-messages');
  const chatEmpty = document.querySelector('#chat-empty');
  const chatStatus = document.querySelector('#chat-status');
  const chatSend = document.querySelector('#chat-send');
  let conversationId = null;
  let conversationVersion = 0;
  let chatSelection = 0;
  let firstMessageId = null;
  const conversationSelect = $('#chat-conversation');
  const networkSelect = $('#chat-network');
  const newChatButton = $('#chat-new');
  const olderChatButton = $('#chat-older');
  function configureUser(user) {
    $('#chat-scope').textContent = user.roles.includes('admin') ? 'Administración' : user.roles.some((r) => ['tecnico', 'operador'].includes(r)) ? 'Soporte técnico' : user.roles.includes('cliente') ? 'Mis redes' : 'Monitoreo';
    restoreChat();
  }
  function appendChatMessage(role, content) {
    chatEmpty.hidden = true;
    const message = document.createElement('article');
    message.className = `chat-message chat-message-${role}`;
    const text = document.createElement('p');
    text.textContent = content;
    message.append(text);
    chatMessages.append(message);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return message;
  }

  function setChatStatus(message, isError = false) {
    chatStatus.textContent = message;
    chatStatus.classList.toggle('is-error', isError);
  }

  function resetChat() {
    chatSelection += 1;
    conversationId = null;
    conversationVersion = 0;
    firstMessageId = null;
    conversationSelect.replaceChildren(new Option('Nueva conversación', ''));
    networkSelect.replaceChildren(new Option('Mis redes autorizadas', ''));
    chatMessages.replaceChildren(chatEmpty);
    chatEmpty.hidden = false;
    chatInput.value = '';
    chatInput.disabled = false;
    chatSend.disabled = false;
    conversationSelect.disabled = false;
    newChatButton.disabled = false;
    networkSelect.disabled = false;
    olderChatButton.hidden = true;
    setChatStatus('');
  }

  async function restoreChat() {
    const session = state.session;
    const selection = chatSelection;
    chatSend.disabled = chatInput.disabled = true;
    try {
      const [conversations, networks] = await Promise.all([
        authedRequest('/api/v1/chat/conversations'),
        state.user.permissions?.includes('networks:read:own') ? authedRequest('/api/v1/networks') : [],
      ]);
      if (session !== state.session || selection !== chatSelection) return;
      networkSelect.replaceChildren(new Option('Mis redes autorizadas', ''), ...networks.map((n) => new Option(`${n.name} · ${n.ssid}`, n.id)));
      onNetworksLoaded(networks);
      conversationSelect.replaceChildren(new Option('Nueva conversación', ''), ...conversations.map((c) => new Option(c.title, c.id)));
      if (conversations.length) {
        conversationSelect.value = conversations[0].id;
        await loadConversation(conversations[0].id);
      } else chatSend.disabled = chatInput.disabled = false;
    } catch (error) {
      if (session === state.session && selection === chatSelection) {
        setChatStatus(`No se pudo recuperar el historial: ${error.message}`, true);
        chatSend.disabled = chatInput.disabled = false;
      }
    }
  }

  async function loadConversation(id, older = false) {
    onConversationChanged();
    const session = state.session;
    const selection = ++chatSelection;
    chatSend.disabled = chatInput.disabled = true;
    try {
      const suffix = older && firstMessageId ? `?before_id=${firstMessageId}` : '';
      const conversation = await authedRequest(`/api/v1/chat/conversations/${id}${suffix}`);
      if (session !== state.session || selection !== chatSelection) return;
      conversationId = conversation.id;
      conversationVersion = conversation.version;
      if (!older) chatMessages.replaceChildren(chatEmpty);
      const oldNodes = older ? [...chatMessages.children] : [];
      if (older) chatMessages.replaceChildren();
      for (const turn of conversation.messages) appendChatMessage(turn.role, turn.content);
      if (older) chatMessages.append(...oldNodes);
      firstMessageId = conversation.messages[0]?.id ?? firstMessageId;
      olderChatButton.hidden = conversation.messages.length < 100;
      chatEmpty.hidden = !!chatMessages.querySelector('.chat-message');
      networkSelect.value = conversation.network_id ?? '';
      networkSelect.disabled = true;
      setChatStatus('Conversación recuperada.');
    } catch (error) {
      if (session === state.session && selection === chatSelection) {
        conversationId = null;
        conversationVersion = 0;
        firstMessageId = null;
        chatMessages.replaceChildren(chatEmpty);
        chatEmpty.hidden = false;
        setChatStatus(error.message, true);
      }
    } finally {
      if (session === state.session && selection === chatSelection) {
        chatSend.disabled = chatInput.disabled = false;
        conversationSelect.disabled = newChatButton.disabled = false;
      }
    }
  }

  conversationSelect.addEventListener('change', () => {
    if (conversationSelect.value) loadConversation(conversationSelect.value);
    else startNewChat();
  });

  function startNewChat() {
    onConversationChanged();
    chatSelection += 1;
    conversationId = null;
    conversationVersion = 0;
    firstMessageId = null;
    chatInput.value = "";
    chatInput.disabled = false;
    conversationSelect.value = '';
    networkSelect.disabled = false;
    chatMessages.replaceChildren(chatEmpty);
    chatEmpty.hidden = false;
    olderChatButton.hidden = true;
    chatSend.disabled = false;
    setChatStatus('Nueva conversación. Elige una red o consulta tus redes autorizadas.');
  }

  newChatButton.addEventListener('click', startNewChat);
  olderChatButton.addEventListener('click', () => conversationId && loadConversation(conversationId, true));

  chatForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const message = chatInput.value.trim();
    if (!message || chatSend.disabled || !state.user) return;
    const session = state.session;
    const selection = chatSelection;
    const current = () => session === state.session && selection === chatSelection;
    const pendingMessage = appendChatMessage('user', message);
    chatInput.value = '';
    chatSend.disabled = chatInput.disabled = true;
    conversationSelect.disabled = newChatButton.disabled = networkSelect.disabled = true;
    setChatStatus('Consultando…');
    try {
      if (!conversationId) {
        const conversation = await authedRequest('/api/v1/chat/conversations', {
          method: 'POST', body: JSON.stringify({ network_id: networkSelect.value ? Number(networkSelect.value) : null }),
        });
        if (!current()) return;
        conversationId = conversation.id;
        conversationVersion = conversation.version;
        conversationSelect.append(new Option(message.slice(0, 100), conversation.id));
        conversationSelect.value = conversation.id;
      }
      const response = await authedRequest('/api/v1/chat/messages', {
        method: 'POST', body: JSON.stringify({ message, conversation_id: conversationId, version: conversationVersion }),
      });
      if (!current()) return;
      conversationVersion = response.version;
      appendChatMessage('assistant', response.answer);
      if (response.reservation_proposal && canReserveVlans(state.user?.roles || [])) renderReservationProposal(response.reservation_proposal);
      if (response.wifi_access_action) renderAccessAction(response.wifi_access_action);
      if (response.ticket_proposal) renderTicketProposal(response.ticket_proposal);
      setChatStatus('Consulta guardada.');
    } catch (error) {
      if (!current()) return;
      pendingMessage.remove();
      chatInput.value = message;
      setChatStatus(error.message || 'No se pudo completar la consulta.', true);
      if ([403, 404, 409].includes(error.status)) {
        // Descartar el contexto visible rechazado antes de recuperar la lista autorizada.
        startNewChat();
        chatInput.disabled = false;
        conversationSelect.disabled = newChatButton.disabled = false;
        await restoreChat();
      }
    } finally {
      if (current()) {
        chatSend.disabled = chatInput.disabled = false;
        conversationSelect.disabled = newChatButton.disabled = false;
        networkSelect.disabled = !!conversationId;
        chatInput.focus();
      }
    }
  });


  return { configureUser, reset: resetChat, loadConversation, startNewChat, capture: () => ({session: state.session, selection: chatSelection}), isCurrent: (context) => context.session === state.session && context.selection === chatSelection, get conversationId() { return conversationId; }, get conversationVersion() { return conversationVersion; } };
}
