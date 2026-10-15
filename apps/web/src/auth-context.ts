import { createContext, useContext } from "react";
import type { Profile } from "./api";

export interface AuthState {
  user: Profile | null;
  loading: boolean;
  restoreError: string;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}
export const AuthContext = createContext<AuthState | null>(null);
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("AuthProvider is required");
  return context;
}
