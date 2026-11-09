import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { ApiError } from "@/api/client";
import { App } from "@/App";
import { AuthProvider, wygaslaSesja } from "@/auth";
import { ToastProvider, toastGlobal } from "@/components/toast";
import { DateRangeProvider } from "@/contexts/dateRange";
import { ThemeProvider } from "@/theme";
import "@fontsource-variable/inter";
import "@/index.css";

/** 401 z dowolnego zapytania = sesja wygasła. Czyścimy stan i wracamy na ekran logowania.
 *
 * Wcześniej 401 był tylko wyciszany: panel zostawał otwarty i pokazywał puste wykresy
 * oraz zera, więc wyglądał jak biznes bez ani jednego zamówienia.
 */
function czyWygaslaSesja(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.status !== 401) return false;
  // Pulpit wysyła 8 zapytań równolegle, a `onError` woła się dla KAŻDEGO z osobna.
  // `wygaslaSesja()` zwraca true tylko przy PIERWSZYM 401 - bez tego użytkownik dostawał
  // 8 nakładających się identycznych komunikatów i 8× czyszczenie cache'u.
  if (wygaslaSesja()) {
    queryClient.clear();
    toastGlobal("Sesja wygasła - zaloguj się ponownie.", "error");
  }
  return true;
}

function obsluzBladZapytania(err: unknown) {
  if (czyWygaslaSesja(err)) return;
  toastGlobal(err instanceof Error ? err.message : "Błąd pobierania danych", "error");
}

// Dla mutacji reagujemy WYŁĄCZNIE na 401 - pozostałe błędy mają własne komunikaty
// w miejscu wywołania, a drugi globalny toast tylko by je dublował.
function obsluzBladMutacji(err: unknown) {
  czyWygaslaSesja(err);
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false, staleTime: 30_000 },
  },
  queryCache: new QueryCache({ onError: obsluzBladZapytania }),
  mutationCache: new MutationCache({ onError: obsluzBladMutacji }),
});

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <ToastProvider>
              <DateRangeProvider>
                <App />
              </DateRangeProvider>
            </ToastProvider>
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
