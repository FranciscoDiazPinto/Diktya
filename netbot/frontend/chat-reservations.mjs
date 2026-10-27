export function canReserveVlans(roles = []) {
  return roles.includes('admin');
}

export function reservationPayload(values) {
  return {
    parent_interface: String(values.parent_interface),
    tag: Number(values.tag),
    event_name: String(values.event_name).trim(),
    purpose: String(values.purpose).trim(),
    ssid: String(values.ssid).trim(),
  };
}
