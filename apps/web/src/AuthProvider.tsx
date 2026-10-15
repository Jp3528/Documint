import { useEffect, useRef, useState, type ReactNode } from "react";
import * as api from "./api";
import { AuthContext } from "./auth-context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<api.Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [restoreError, setRestoreError] = useState("");
  const epoch = useRef(0);
  useEffect(() => {
    let alive = true;
    const initialEpoch = epoch.current;
    void api
      .refreshAccess()
      .then(api.getProfile)
      .then((profile) => {
        if (alive && initialEpoch === epoch.current) setUser(profile);
      })
      .catch((error) => {
        if (alive && !(error instanceof api.ApiError && error.status === 401))
          setRestoreError(api.errorMessage(error));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    const unsubscribe = api.onSessionExpired(() => {
      epoch.current++;
      setUser(null);
    });
    const refreshProfile = () => {
      const before = epoch.current;
      void api
        .getProfile()
        .then((profile) => {
          if (alive && before === epoch.current) setUser(profile);
        })
        .catch(() => undefined);
    };
    const permissions = api.onPermissionsChanged(refreshProfile);
    return () => {
      alive = false;
      unsubscribe();
      permissions();
    };
  }, []);
  useEffect(() => {
    if (!user) return;
    let alive = true;
    const focus = () => {
      const before = epoch.current;
      void api
        .getProfile()
        .then((profile) => {
          if (alive && before === epoch.current) setUser(profile);
        })
        .catch(() => undefined);
    };
    window.addEventListener("focus", focus);
    return () => {
      alive = false;
      window.removeEventListener("focus", focus);
    };
  }, [user]);
  return (
    <AuthContext
      value={{
        user,
        loading,
        restoreError,
        login: async (email, password) => {
          epoch.current++;
          const profile = await api.login(email, password);
          setUser(profile);
          setRestoreError("");
        },
        logout: async () => {
          epoch.current++;
          await api.logout();
          setUser(null);
        },
      }}
    >
      {children}
    </AuthContext>
  );
}
