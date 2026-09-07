/** Sign-in. Dev mode: one-click as the configured dev user. Google mode: redirect to /auth/google/login. */
import { useLocation, useNavigate } from "react-router-dom";
import { auth } from "../lib/api";
import { useSession } from "../lib/session";

export function Login() {
  const { config, refresh, user } = useSession();
  const nav = useNavigate();
  const loc = useLocation();
  const denied = new URLSearchParams(loc.search).get("denied");
  const from = (loc.state as { from?: string } | null)?.from ?? "/library";

  if (user) {
    nav(from, { replace: true });
    return null;
  }

  return (
    <div className="login">
      <div className="box">
        <h1>Protocol Studio</h1>
        <p>Clinical-trial protocols and SAPs, structured to ICH M11, with a source-traceable trial model.</p>
        {denied && <p className="err">Your account is not yet authorised. Ask an administrator (ben@sarika.com) to activate it.</p>}
        {config?.auth_mode === "google" ? (
          <a className="btn primary" href="/auth/google/login">
            Sign in with Google ({config.allowed_domain})
          </a>
        ) : (
          <button
            className="btn primary"
            onClick={async () => {
              await auth.devLogin();
              await refresh();
              nav(from, { replace: true });
            }}
          >
            Continue as the development user
          </button>
        )}
        <p className="tiny">Only @{config?.allowed_domain ?? "sarika.com"} accounts that an administrator has activated can sign in.</p>
      </div>
    </div>
  );
}
