import * as React from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "@/auth";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Layout } from "@/components/Layout";
import { Spinner } from "@/components/ui";
import { Login } from "@/pages/Login";

// Lazy-load stron (code-splitting per trasa; recharts trafia do osobnego chunku).
const lazyNamed = <K extends string>(loader: () => Promise<Record<K, React.ComponentType>>, name: K) =>
  React.lazy(() => loader().then((m) => ({ default: m[name] })));

const Dashboard = lazyNamed(() => import("@/pages/Dashboard"), "Dashboard");
const Orders = lazyNamed(() => import("@/pages/Orders"), "Orders");
const Companies = lazyNamed(() => import("@/pages/Companies"), "Companies");
const CompanyProfile = lazyNamed(() => import("@/pages/CompanyProfile"), "CompanyProfile");
const Inbox = lazyNamed(() => import("@/pages/Inbox"), "Inbox");
const Marketing = lazyNamed(() => import("@/pages/Marketing"), "Marketing");
const Competitors = lazyNamed(() => import("@/pages/Competitors"), "Competitors");
const Recommendations = lazyNamed(() => import("@/pages/Recommendations"), "Recommendations");
const Reports = lazyNamed(() => import("@/pages/Reports"), "Reports");
const Settings = lazyNamed(() => import("@/pages/Settings"), "Settings");

export function App() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Ładowanie…" />
      </div>
    );
  }

  if (!user) return <Login />;

  return (
    <ErrorBoundary>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="zamowienia" element={<Orders />} />
          <Route path="firmy" element={<Companies />} />
          <Route path="firmy/:id" element={<CompanyProfile />} />
          <Route path="skrzynka" element={<Inbox />} />
          <Route path="marketing" element={<Marketing />} />
          <Route path="konkurencja" element={<Competitors />} />
          <Route path="rekomendacje" element={<Recommendations />} />
          <Route path="raporty" element={<Reports />} />
          <Route path="ustawienia" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  );
}
