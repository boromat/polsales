// Lekki system powiadomień (toasty) - provider + hook useToast. Bez zależności.
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

type ToastLevel = "success" | "error" | "info";
interface Toast {
  id: number;
  level: ToastLevel;
  message: string;
}

interface ToastApi {
  push: (message: string, level?: ToastLevel) => void;
  success: (m: string) => void;
  error: (m: string) => void;
  info: (m: string) => void;
}

const ToastContext = React.createContext<ToastApi | null>(null);

// Most globalny - pozwala pokazać toast spoza drzewa React (np. QueryCache.onError w main.tsx).
let _globalPush: ((message: string, level?: ToastLevel) => void) | null = null;
export function toastGlobal(message: string, level: ToastLevel = "info") {
  _globalPush?.(message, level);
}

let _id = 1;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);

  const remove = React.useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const push = React.useCallback(
    (message: string, level: ToastLevel = "info") => {
      const id = _id++;
      setToasts((t) => [...t, { id, level, message }]);
      setTimeout(() => remove(id), 5000);
    },
    [remove],
  );

  const api = React.useMemo<ToastApi>(
    () => ({
      push,
      success: (m) => push(m, "success"),
      error: (m) => push(m, "error"),
      info: (m) => push(m, "info"),
    }),
    [push],
  );

  React.useEffect(() => {
    _globalPush = push;
    return () => {
      _globalPush = null;
    };
  }, [push]);

  const tone: Record<ToastLevel, string> = {
    success: "border-success/30 bg-success-soft text-success",
    error: "border-danger/30 bg-danger-soft text-danger",
    info: "border-border bg-surface text-text",
  };
  const Icon = { success: CheckCircle2, error: AlertCircle, info: Info } as const;

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[min(92vw,360px)] flex-col gap-2">
        {toasts.map((t) => {
          const I = Icon[t.level];
          return (
            <div
              key={t.id}
              className={cn(
                "pointer-events-auto flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm shadow-pop animate-fade-in-up",
                tone[t.level],
              )}
              role="status"
            >
              <I className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="flex-1">{t.message}</span>
              <button onClick={() => remove(t.id)} className="shrink-0 opacity-60 hover:opacity-100">
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = React.useContext(ToastContext);
  if (!ctx) throw new Error("useToast poza ToastProvider");
  return ctx;
}
