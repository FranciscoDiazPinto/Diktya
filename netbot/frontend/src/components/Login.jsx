import { useRef, useState } from "react";
import { GoogleSignIn } from "./GoogleSignIn.jsx";
export function Login({ login, loginGoogle, api, onBack, message }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [visible, setVisible] = useState(false);
  const pending = useRef(false);
  const passwordField = useRef(null);
  async function submit(event) {
    event.preventDefault();
    if (pending.current) return;
    const form = event.currentTarget,
      data = new FormData(form);
    pending.current = true;
    setBusy(true);
    setError("");
    // The password is never stored in React state or browser persistence.
    const password = form.elements.password;
    const value = data.get("password");
    password.value = "";
    try {
      await login(data.get("email"), value);
    } catch (e) {
      setError(
        e.status === 401
          ? "El correo o la contraseña no son correctos."
          : "No se pudo conectar con la API. Inténtalo nuevamente.",
      );
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  async function googleCredential(credential, challengeToken) {
    if (pending.current) return;
    if (passwordField.current) passwordField.current.value = "";
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      await loginGoogle(credential, challengeToken);
    } catch (e) {
      setError(
        e.status === 503
          ? "Google no está disponible. Inténtalo nuevamente."
          : "No fue posible autorizar esta cuenta de Google. Solicita acceso al administrador.",
      );
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="login-screen" id="login-screen">
      <div className="login-aside">
        <div className="brand login-brand">
          <strong>netbot</strong>
          <small>network intelligence</small>
        </div>
        <div className="login-aside-copy">
          <p className="eyebrow">CENTRO DE MONITOREO</p>
          <h1>
            Tu red,
            <br />
            <em>bajo control.</em>
          </h1>
          <p>
            Consulta tu infraestructura y gestiona las acciones autorizadas.
          </p>
        </div>
      </div>
      <div className="login-form-wrap">
        <form className="login-form" id="login-form" onSubmit={submit}>
          <button type="button" id="guest-back" onClick={onBack}>
            ← Volver al chat de invitados
          </button>
          <h2>Iniciar sesión</h2>
          <label htmlFor="email">Correo electrónico</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            autoFocus
          />
          <label htmlFor="password">Contraseña</label>
          <div className="password-field">
            <input
              id="password"
              ref={passwordField}
              name="password"
              type={visible ? "text" : "password"}
              autoComplete="current-password"
              required
            />
            <button
              id="toggle-password"
              type="button"
              aria-label={visible ? "Ocultar contraseña" : "Mostrar contraseña"}
              onClick={() => setVisible(!visible)}
            >
              {visible ? "Ocultar" : "Mostrar"}
            </button>
          </div>
          <p className="login-error" id="login-error" role="alert">
            {error || message}
          </p>
          <button
            className="login-submit"
            id="login-submit"
            disabled={busy}
            type="submit"
          >
            {busy ? "Conectando…" : "Ingresar"}
          </button>
          {!busy && api && (
            <GoogleSignIn api={api} onCredential={googleCredential} />
          )}
          <p className="login-note">
            La sesión permanece en memoria y caduca automáticamente.
          </p>
        </form>
      </div>
    </section>
  );
}
