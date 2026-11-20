import { useLayoutEffect, useRef } from "react";
import { createGuest } from "../../modules/guest.mjs";
import { createControllerScope } from "../runtime/controller-scope.mjs";
import { GuestMarkup } from "./FeatureMarkup.jsx";
export function Guest({ runtime, onLogin }) {
  const root = useRef(null);
  useLayoutEffect(() => {
    const scope = createControllerScope(root.current, runtime);
    const guest = createGuest({ ...scope, onLogin });
    guest.start();
    scope.finishMount();
    return () => {
      scope.dispose();
      guest.stop();
    };
  }, [runtime, onLogin]);
  return (
    <div ref={root}>
      <GuestMarkup />
    </div>
  );
}
