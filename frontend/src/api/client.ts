// Cienki klient fetch do /api/*. Cookie sesji leci automatycznie (credentials: include).

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Pole `detail` z FastAPI zamienione na jedno zdanie po polsku.
 *
 * Dla błędu walidacji (HTTP 422) FastAPI zwraca TABLICĘ obiektów
 * `{loc, msg, type}`, a nie tekst. Wstawiona wprost do `Error.message` dawała
 * użytkownikowi „[object Object]" zamiast informacji, które pole jest złe.
 */
export function czytelnyBlad(detail: unknown): string | null {
  if (detail == null) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const czesci = detail
      .map((d) => {
        if (typeof d === "string") return d;
        if (d && typeof d === "object") {
          const w = d as { loc?: unknown[]; msg?: string };
          // loc = ["body", "items", 0, "quantity"] → pomijamy pierwszy element ("body").
          const pole = Array.isArray(w.loc) ? w.loc.slice(1).join(".") : "";
          if (w.msg) return pole ? `${pole}: ${w.msg}` : w.msg;
        }
        return null;
      })
      .filter(Boolean);
    return czesci.length ? czesci.join("; ") : null;
  }
  if (typeof detail === "object") {
    const w = detail as { msg?: string; message?: string };
    return w.msg ?? w.message ?? JSON.stringify(detail);
  }
  return String(detail);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = czytelnyBlad(data.detail) ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

// --- Typy odpowiedzi ---
export interface User {
  id: number;
  username: string;
}

export interface Kpi {
  revenue_net: number;
  orders_count: number;
  avg_order_value_net: number | null;
  avg_ltv_net: number | null;
  cac: number | null;
  roas: number | null;
  avg_lead_time_days: number | null;
  ad_spend: number | null;
  gross_margin_net: number | null;
  margin_pct: number | null;
}

export interface BusinessAlert {
  level: "info" | "warning" | "danger";
  title: string;
  detail: string;
}

export interface RevenuePoint {
  date: string;
  revenue_net: number;
  orders_count: number;
}

export interface Order {
  id: number;
  order_no: string;
  company_id: number | null;
  company_name: string | null;
  contact_id: number | null;
  source: string;
  status: string;
  ordered_at: string;
  total_gross: number;
  total_net: number;
  total_vat: number;
  attribution_channel_id: number | null;
  notes: string | null;
}

export interface OrderItem {
  id: number;
  product_id: number | null;
  description: string | null;
  quantity: number;
  unit_price_gross: number;
  vat_rate: number;
  line_gross: number;
  line_net: number;
  line_vat: number;
}

export interface OrderDetail extends Order {
  items: OrderItem[];
}

export interface CompanyListItem {
  company_id: number;
  company_name: string | null;
  nip: string | null;
  ltv_net: number | null;
  orders_count: number | null;
  frequency_days: number | null;
  last_order: string | null;
  avg_order_value_net: number | null;
  avg_lead_time_days: number | null;
  days_since_last_order?: number | null;
  at_risk?: boolean | null;
}

export interface CompanyProfile extends CompanyListItem {
  first_order: string | null;
  orders: Order[];
}

export interface Channel {
  id: number;
  code: string;
  name_pl: string;
  is_paid: boolean;
}

export interface IntegrationStatus {
  source: string;
  state: string;
  last_ok: string | null;
  message: string | null;
}

// --- Szkice (Etap 2) ---
/** Mail rozpoznany jako zamówienie, którego nie udało się odczytać (nie ma szkicu). */
export interface ProblemEmail {
  id: number;
  from_addr: string | null;
  from_name: string | null;
  subject: string | null;
  date_received: string | null;
  error_detail: string | null;
  classification_reason: string | null;
  body_preview: string;
}

/** Zgłoszenie współpracy ze strony (klub sportowy / hurtownik) - nie zamówienie, bez szkicu. */
export interface PartnerEmail {
  id: number;
  date_received: string | null;
  subject: string | null;
  kind: string | null;
  company_name: string | null;
  nip: string | null;
  contact_person: string | null;
  email: string | null;
  phone: string | null;
  region: string | null;
  form: string | null;
  message: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
}

export interface DraftListItem {
  id: number;
  created_at: string;
  from_addr: string | null;
  subject: string | null;
  extraction_method: string;
  extraction_confidence: number | null;
  status: string;
  company_name: string | null;
  nip: string | null;
  items_count: number;
}

export interface DraftItem {
  id: number;
  raw_name: string | null;
  quantity: number | null;
  unit: string | null;
  matched_product_id: number | null;
  match_status: string;
  match_score: number | null;
  variant_notes: string | null;
}

export interface DraftEmail {
  from_addr: string | null;
  from_name: string | null;
  subject: string | null;
  date_received: string | null;
  body_text: string | null;
  has_attachments: boolean;
  is_form: boolean;
}

export interface DraftDetail {
  id: number;
  status: string;
  extraction_method: string;
  extraction_confidence: number | null;
  nip: string | null;
  company_name: string | null;
  contact_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  attribution_method: string | null;
  ambiguities: string[];
  items: DraftItem[];
  email: DraftEmail | null;
}

export interface Product {
  id: number;
  sku: string | null;
  name: string;
  vat_rate_id: number;
  default_price_gross: number | null;
  is_active: boolean;
}

// --- Marketing (Etap 3) ---
export interface Funnel {
  impressions: number;
  clicks: number;
  sessions: number;
  orders: number;
  revenue_net: number;
  spend: number;
  ctr: number | null;
  click_to_session: number | null;
  cr_session_order: number | null;
  cpc: number | null;
  cpo: number | null;
  roas: number | null;
}

export interface ChannelSummary {
  channel_code: string;
  name_pl: string;
  spend: number;
  sessions: number;
  orders: number;
  revenue_net: number;
  roas: number | null;
}

// --- Domknięcie zakresu (Etap 7) ---
export interface AdFormat {
  platform: string;
  kind: string; // platny | organiczny
  format: string;
  impressions: number;
  clicks: number;
  spend: number;
  views: number;
  engagement: number;
  ctr: number | null;
  engagement_rate: number | null;
}

export interface OrganicByType {
  post_type: string;
  posts: number;
  views: number;
  reach: number;
  likes: number;
  comments: number;
  shares: number;
  link_clicks: number;
  engagement: number;
  engagement_rate: number | null;
}

export interface OrganicEngagement {
  by_type: OrganicByType[];
  totals: {
    posts: number;
    views: number;
    reach: number;
    likes: number;
    comments: number;
    shares: number;
    link_clicks: number;
    engagement: number;
    engagement_rate: number | null;
  };
}

export interface EmailTrend {
  product: string;
  mentions: number;
  quantity: number;
  days: number;
}

export interface WeeklySummary {
  week_start: string;
  week_end: string;
  headline: string;
  body: string;
  metrics: Record<string, unknown> | null;
  created_at: string;
  model: string | null;
}

export interface IntegrationsConfig {
  imap: boolean;
  meta_ads: boolean;
  meta_organic: boolean;
  ga4: boolean;
  google_ads: boolean;
  anthropic: boolean;
  /** Aktywny dostawca AI: "openrouter" | "anthropic" | "custom" (własny endpoint) | "" (brak). */
  ai_provider: string;
  smtp: boolean;
  chat_model: string;
  email_parser_model: string;
  /** Czy dane osobowe są maskowane (polanon) przed wysłaniem do AI. */
  pii_masking: boolean;
  /** Komunikat o brakującym extra "google" dla GA4 / Google Ads albo null, gdy pakiety są. */
  missing_packages: Partial<Record<"ga4" | "google_ads", string | null>>;
}

/** Maskowanie danych osobowych przed AI (Ustawienia -> Prywatność AI). */
export interface PrivacyStatus {
  enabled: boolean;
  ner: boolean;
  polanon: { installed: boolean; version: string | null; ner: boolean };
  /** Włączone, a polanon niedostępny: funkcje AI są zablokowane (fail closed). */
  blocking: boolean;
}
