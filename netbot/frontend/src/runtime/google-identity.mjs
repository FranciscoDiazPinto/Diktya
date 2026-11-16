// Only the SDK-loading promise is shared, never accounts, nonces or credentials.
let loading;
export function loadGoogleIdentity() {
  if (window.google?.accounts?.id)
    return Promise.resolve(window.google.accounts.id);
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    const fail = () => {
      clearTimeout(timer);
      script.remove();
      loading = null;
      reject(new Error("No fue posible cargar el acceso con Google."));
    };
    const timer = setTimeout(fail, 10000);
    script.onerror = fail;
    script.onload = () => {
      clearTimeout(timer);
      if (!window.google?.accounts?.id) {
        fail();
        return;
      }
      resolve(window.google.accounts.id);
    };
    document.head.append(script);
  });
  return loading;
}
