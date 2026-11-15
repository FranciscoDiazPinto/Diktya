// Adapt imperative feature controllers to a React mount. No global singleton state.
// Each mount owns listeners, timers and a session view invalidated on disposal.
export function createControllerScope(root, runtime) {
  const owner = root.ownerDocument,
    host = owner.defaultView;
  let disposed = false;
  const timeouts = new Set(),
    intervals = new Set(),
    listeners = [];
  const listen = (target, type, callback, options) => {
    target.addEventListener(type, callback, options);
    listeners.push(() => target.removeEventListener(type, callback, options));
  };
  // Existing controllers register listeners on elements during construction.
  // Restore the methods after mounting; remove registered callbacks on unmount.
  const restores = [...root.querySelectorAll("*")].map((node) => {
    const original = node.addEventListener;
    node.addEventListener = function (type, callback, options) {
      original.call(this, type, callback, options);
      listeners.push(() => this.removeEventListener(type, callback, options));
    };
    return () => {
      delete node.addEventListener;
    };
  });
  const window = new Proxy(host, {
    get(target, key) {
      if (key === "setTimeout")
        return (fn, ms) => {
          if (disposed) return 0;
          const id = host.setTimeout(() => {
            timeouts.delete(id);
            if (!disposed) fn();
          }, ms);
          timeouts.add(id);
          return id;
        };
      if (key === "setInterval")
        return (fn, ms) => {
          if (disposed) return 0;
          const id = host.setInterval(() => {
            if (!disposed) fn();
          }, ms);
          intervals.add(id);
          return id;
        };
      if (key === "clearTimeout")
        return (id) => {
          timeouts.delete(id);
          host.clearTimeout(id);
        };
      if (key === "clearInterval")
        return (id) => {
          intervals.delete(id);
          host.clearInterval(id);
        };
      if (key === "addEventListener") return (...args) => listen(host, ...args);
      if (key === "URL") return target.URL;
      const value = Reflect.get(target, key);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
  const document = new Proxy(owner, {
    get(target, key) {
      if (key === "querySelector")
        return (selector) => root.querySelector(selector);
      if (key === "querySelectorAll")
        return (selector) => root.querySelectorAll(selector);
      if (key === "addEventListener")
        return (...args) => listen(owner, ...args);
      const value = Reflect.get(target, key);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
  const state = {
    get session() {
      return disposed ? -1 : runtime.state.session;
    },
    get user() {
      return disposed ? null : runtime.state.user;
    },
  };
  return {
    document,
    window,
    state,
    api: runtime.api,
    Option: host.Option,
    crypto: host.crypto,
    FormData: host.FormData,
    finishMount() {
      restores.splice(0).forEach((restore) => restore());
    },
    dispose() {
      disposed = true;
      restores.splice(0).forEach((restore) => restore());
      listeners.splice(0).forEach((remove) => remove());
      timeouts.forEach((id) => host.clearTimeout(id));
      timeouts.clear();
      intervals.forEach((id) => host.clearInterval(id));
      intervals.clear();
    },
  };
}
