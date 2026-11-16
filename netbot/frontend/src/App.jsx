import {
  Component,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSession } from "./hooks/useSession.jsx";
import { Workspace } from "./components/Workspace.jsx";
import { Guest } from "./components/Guest.jsx";
import { Login } from "./components/Login.jsx";
export class ErrorBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <main className="login-form">
        <h1>No se pudo abrir la interfaz</h1>
        <p>Recarga la página para iniciar una sesión nueva.</p>
        <button onClick={() => location.reload()}>Recargar</button>
      </main>
    ) : (
      this.props.children
    );
  }
}
export default function App({ fetcher, storage }) {
  const session = useSession({ fetcher, storage });
  const [toast, setToast] = useState(""),
    timer = useRef(null);
  const notify = useCallback((text) => {
    clearTimeout(timer.current);
    setToast(text);
    timer.current = setTimeout(() => setToast(""), 2200);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);
  const runtime = useMemo(
    () => ({
      state: session.state,
      api: session.api,
      signOut: session.signOut,
      notify,
    }),
    [session.state, session.api, session.signOut, notify],
  );
  const loginScreen = useCallback(
    () => session.openScreen("login"),
    [session.openScreen],
  );
  const guestScreen = useCallback(
    () => session.openScreen("guest"),
    [session.openScreen],
  );
  return (
    <ErrorBoundary>
      {session.user ? (
        <Workspace key={session.state.session} runtime={runtime} />
      ) : session.screen === "guest" ? (
        <Guest runtime={runtime} onLogin={loginScreen} />
      ) : (
        <Login
          login={session.login}
          loginGoogle={session.loginGoogle}
          api={session.api}
          onBack={guestScreen}
          message={session.message}
        />
      )}
      <div className={"toast" + (toast ? " show" : "")} role="status">
        {toast}
      </div>
    </ErrorBoundary>
  );
}
