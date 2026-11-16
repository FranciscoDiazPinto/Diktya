import { useEffect, useRef, useState } from "react";
import { loadGoogleIdentity } from "../runtime/google-identity.mjs";

export function GoogleSignIn({ api, onCredential }) {
  const target = useRef(null),
    callback = useRef(onCredential);
  callback.current = onCredential;
  const [state, setState] = useState("loading"),
    [message, setMessage] = useState(""),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true,
      accepting = true,
      timer;
    const aborter = new AbortController();
    const container = target.current;
    setState("loading");
    setMessage("");
    container.replaceChildren();
    (async () => {
      try {
        const config = await api.apiRequest("/auth/google/config", {
          signal: aborter.signal,
        });
        if (!live) return;
        if (!config.enabled) {
          setState("disabled");
          return;
        }
        const [challenge, identity] = await Promise.all([
          api.apiRequest("/auth/google/challenge", {
            method: "POST",
            signal: aborter.signal,
          }),
          loadGoogleIdentity(),
        ]);
        if (!live) return;
        identity.initialize({
          client_id: config.client_id,
          nonce: challenge.nonce,
          auto_select: false,
          callback: (result) => {
            if (!live || !accepting || !result.credential) return;
            accepting = false;
            clearTimeout(timer);
            callback.current(result.credential, challenge.challenge_token);
          },
        });
        identity.renderButton(container, {
          theme: "outline",
          size: "large",
          text: "continue_with",
          locale: "es",
        });
        setState("ready");
        timer = setTimeout(
          () => {
            if (!live) return;
            accepting = false;
            container.replaceChildren();
            setState("error");
            setMessage(
              "La solicitud de acceso con Google venció. Iníciala nuevamente.",
            );
          },
          Math.min(Number(challenge.expires_in) || 300, 300) * 1000,
        );
      } catch {
        if (live) {
          container.replaceChildren();
          setState("error");
          setMessage(
            "Google no está disponible. Puedes reintentar o ingresar con tu contraseña.",
          );
        }
      }
    })();
    return () => {
      live = false;
      accepting = false;
      aborter.abort();
      clearTimeout(timer);
      container.replaceChildren();
    };
  }, [api, retry]);
  return (
    <div className="google-sign-in" hidden={state === "disabled"}>
      <div ref={target} aria-label="Acceso con Google" />
      {state === "ready" && (
        <p className="login-note">
          Solo cuentas corporativas previamente autorizadas.
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {state === "error" && (
        <button type="button" onClick={() => setRetry((v) => v + 1)}>
          Reintentar acceso con Google
        </button>
      )}
    </div>
  );
}
