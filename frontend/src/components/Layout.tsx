// Layout hybrydowy, responsywny: sidebar (drawer na telefonie, statyczny 248px na desktopie)
// + treść + panel czatu (pełny ekran na telefonie, dokowany 420px na desktopie). Ctrl+K = czat.
import {
  BarChart3,
  Binoculars,
  Building2,
  FileText,
  Inbox,
  LayoutDashboard,
  Lightbulb,
  LogOut,
  Megaphone,
  Menu,
  Moon,
  Settings,
  ShoppingCart,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { api } from "@/api/client";
import { useAuth } from "@/auth";
import { ChatPanel } from "@/components/ChatPanel";
import { Button, Spinner } from "@/components/ui";
import { useTheme } from "@/theme";
import { cn } from "@/lib/utils";
import { pl } from "@/i18n/pl";

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  end?: boolean;
  badge?: "drafts";
};

const NAV_GROUPS: { label: string | null; items: NavItem[] }[] = [
  { label: null, items: [{ to: "/", label: pl.nav.dashboard, icon: LayoutDashboard, end: true }] },
  {
    label: "Sprzedaż",
    items: [
      { to: "/skrzynka", label: pl.nav.inbox, icon: Inbox, badge: "drafts" },
      { to: "/zamowienia", label: pl.nav.orders, icon: ShoppingCart },
      { to: "/firmy", label: pl.nav.companies, icon: Building2 },
    ],
  },
  {
    label: "Marketing",
    items: [
      { to: "/marketing", label: pl.nav.marketing, icon: Megaphone },
      { to: "/konkurencja", label: "Konkurencja", icon: Binoculars },
      { to: "/rekomendacje", label: pl.nav.recommendations, icon: Lightbulb },
      { to: "/raporty", label: "Raporty", icon: FileText },
    ],
  },
  { label: "System", items: [{ to: "/ustawienia", label: pl.nav.settings, icon: Settings }] },
];

const VIEW_NAMES: Record<string, string> = {
  "/": pl.nav.dashboard,
  "/skrzynka": pl.nav.inbox,
  "/zamowienia": pl.nav.orders,
  "/firmy": pl.nav.companies,
  "/marketing": pl.nav.marketing,
  "/rekomendacje": pl.nav.recommendations,
  "/raporty": "Raporty",
  "/ustawienia": pl.nav.settings,
};

export function Layout() {
  const { logout, user } = useAuth();
  const { isDark, toggle: toggleTheme } = useTheme();
  const location = useLocation();
  const draftsCount = useQuery({
    queryKey: ["draftsCount"],
    queryFn: () => api.get<{ pending: number; problems: number; partners?: number }>("/drafts/count"),
    refetchInterval: 30000,
  });
  const [chatOpen, setChatOpen] = React.useState(() => localStorage.getItem("chatOpen") === "1");
  const [mobileNav, setMobileNav] = React.useState(false);

  const setChat = React.useCallback((next: boolean) => {
    setChatOpen(next);
    localStorage.setItem("chatOpen", next ? "1" : "0");
  }, []);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setChat(localStorage.getItem("chatOpen") !== "1");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setChat]);

  // Zamknij szufladę nawigacji po zmianie trasy (telefon).
  React.useEffect(() => setMobileNav(false), [location.pathname]);

  const viewName =
    VIEW_NAMES[location.pathname] ??
    (location.pathname.startsWith("/firmy/") ? "Profil firmy" : pl.nav.dashboard);
  // Plakietka liczy szkice do weryfikacji ORAZ maile, ktorych nie udalo sie odczytac -
  // te drugie tez wymagaja reakcji, a bez tego bylyby widoczne dopiero po wejsciu w Skrzynke.
  const pending = (draftsCount.data?.pending ?? 0) + (draftsCount.data?.problems ?? 0);
  // Zgłoszenia współpracy liczymy OSOBNO i w neutralnym kolorze: to nie zamówienia, więc nie
  // mogą podbijać czerwonej plakietki „do weryfikacji".
  const partners = draftsCount.data?.partners ?? 0;

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Przyciemnienie pod szufladą nawigacji (tylko telefon) */}
      {mobileNav && (
        <div className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm md:hidden" onClick={() => setMobileNav(false)} />
      )}

      {/* Sidebar: szuflada na telefonie, statyczny na desktopie */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-border bg-surface transition-transform duration-200 ease-out",
          "md:static md:z-auto md:w-[248px] md:translate-x-0",
          mobileNav ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-14 items-center gap-2.5 px-4">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#4F46E5] text-white shadow-sm">
            <BarChart3 className="h-[18px] w-[18px]" />
          </span>
          <span className="flex-1 text-[15px] font-semibold tracking-tight">{pl.appName}</span>
          <button
            onClick={() => setMobileNav(false)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-text-muted hover:bg-surface-2 md:hidden"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-3">
          {NAV_GROUPS.map((group, gi) => (
            <div key={gi} className="space-y-1">
              {group.label && (
                <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-text-subtle">
                  {group.label}
                </div>
              )}
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  onClick={() => setMobileNav(false)}
                  className={({ isActive }) =>
                    cn(
                      "group relative flex h-10 items-center gap-3 rounded-lg px-3 text-sm transition-colors",
                      isActive
                        ? "bg-primary-soft font-medium text-primary"
                        : "text-text-muted hover:bg-surface-2 hover:text-text",
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && (
                        <span className="absolute -left-3 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-primary" />
                      )}
                      <item.icon className="h-[18px] w-[18px] shrink-0" />
                      <span className="flex-1 truncate">{item.label}</span>
                      {item.badge === "drafts" && pending > 0 && (
                        <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-danger px-1.5 text-[10px] font-semibold text-white">
                          {pending}
                        </span>
                      )}
                      {item.badge === "drafts" && partners > 0 && (
                        <span
                          title="Zgłoszenia współpracy"
                          className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-surface-2 px-1.5 text-[10px] font-semibold text-text-muted ring-1 ring-inset ring-border"
                        >
                          {partners}
                        </span>
                      )}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="border-t border-border p-3">
          <div className="flex items-center gap-2.5 rounded-lg px-2 py-1.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold text-primary">
              {(user?.username ?? "?").slice(0, 2).toUpperCase()}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{user?.username}</div>
              <div className="text-xs text-text-subtle">Właściciel</div>
            </div>
            <button
              onClick={logout}
              title={pl.common.logout}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-text-subtle transition-colors hover:bg-surface-2 hover:text-danger"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Kolumna treści */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border bg-surface/80 px-4 backdrop-blur md:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <button
              onClick={() => setMobileNav(true)}
              title="Menu"
              className="flex h-10 w-10 items-center justify-center rounded-lg text-text-muted hover:bg-surface-2 md:hidden"
            >
              <Menu className="h-5 w-5" />
            </button>
            <h1 className="truncate text-base font-semibold tracking-tight md:text-[17px]">{viewName}</h1>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <button
              onClick={toggleTheme}
              title={isDark ? "Tryb jasny" : "Tryb ciemny"}
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-text-muted transition-colors hover:bg-surface-2 hover:text-text"
            >
              {isDark ? <Sun className="h-[18px] w-[18px]" /> : <Moon className="h-[18px] w-[18px]" />}
            </button>
            <Button
              variant={chatOpen ? "secondary" : "primary"}
              onClick={() => setChat(!chatOpen)}
              title="Asystent AI (Ctrl+K)"
              className="px-3 md:px-4"
            >
              <Sparkles className="h-4 w-4" />
              <span className="hidden sm:inline">Asystent AI</span>
              <kbd className="ml-1 hidden rounded border border-current/25 px-1 text-[10px] font-normal opacity-70 lg:inline">
                Ctrl K
              </kbd>
            </Button>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-4 md:p-6">
          <div className="mx-auto max-w-[1200px] animate-fade-in">
            <React.Suspense
              fallback={
                <div className="flex min-h-[40vh] items-center justify-center">
                  <Spinner label="Ładowanie…" />
                </div>
              }
            >
              <Outlet />
            </React.Suspense>
          </div>
        </main>
      </div>

      {/* Panel czatu: pełny ekran na telefonie, dokowana kolumna 420px na desktopie */}
      {chatOpen && (
        <aside className="fixed inset-0 z-50 flex flex-col bg-surface md:static md:inset-auto md:z-auto md:w-[420px] md:border-l md:border-border">
          <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4 md:hidden">
            <span className="flex items-center gap-2 text-sm font-semibold">
              <Sparkles className="h-4 w-4 text-primary" /> Asystent AI
            </span>
            <button
              onClick={() => setChat(false)}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-text-muted hover:bg-surface-2"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          <div className="min-h-0 flex-1">
            <ChatPanel viewName={viewName} />
          </div>
        </aside>
      )}
    </div>
  );
}
