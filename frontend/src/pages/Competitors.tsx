// Obserwacja konkurencji w trzech grupach (decyzja #22). Dane wyłącznie publiczne.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, EyeOff, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import { useToast } from "@/components/toast";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  Input,
  Label,
  PageHead,
  Select,
  Skeleton,
  TBody,
  THead,
  Table,
  Td,
  Th,
  Tr,
} from "@/components/ui";
import { useDateRange } from "@/contexts/dateRange";
import { polonizeDecimals } from "@/lib/format";

type Grupa = "europejska" | "polska" | "lokalna";

interface Konkurent {
  id: number;
  grupa: Grupa;
  name: string;
  ig_username: string | null;
  fb_url: string | null;
  www: string | null;
  notes: string | null;
  is_active: boolean;
}

interface ProfilWRaporcie {
  id: number;
  name: string;
  ig_username: string | null;
  www: string | null;
  followers: number | null;
  przyrost_30d_pct: number | null;
  ostatnia_migawka: string | null;
  postow_zebranych: number;
}

interface Format {
  media_type: string;
  postow: number;
  udzial: number;
}

interface TopPost {
  profil: string;
  media_type: string;
  engagement: number;
  likes: number;
  comments: number;
  caption: string;
  permalink: string | null;
  posted_at: string | null;
}

interface GrupaRaport {
  grupa: Grupa;
  nazwa: string;
  profile: ProfilWRaporcie[];
  postow: number;
  profili: number;
  dosc_danych: boolean;
  min_postow: number;
  widoczne: string[];
  niewidoczne: string[];
  mediana_zaangazowania: number | null;
  srednia_zaangazowania: number | null;
  postow_na_tydzien: number | null;
  formaty: Format[];
  top_posty: TopPost[];
}

interface Raport {
  grupy: GrupaRaport[];
  wlasny: { postow: number; postow_na_tydzien: number | null; formaty: Format[]; views_wlasne: number | null };
  profili_lacznie: number;
  postow_lacznie: number;
}

const NAZWY_FORMATOW: Record<string, string> = {
  reel: "Rolka",
  carousel: "Karuzela",
  photo: "Zdjęcie",
  video: "Wideo",
  inny: "Inny",
};

const KOLORY_FORMATOW: Record<string, string> = {
  reel: "bg-primary",
  carousel: "bg-purple-600",
  photo: "bg-emerald-600",
  video: "bg-orange-500",
  inny: "bg-slate-400",
};

const GRUPY: { wartosc: Grupa; etykieta: string }[] = [
  { wartosc: "europejska", etykieta: "Europejska" },
  { wartosc: "polska", etykieta: "Polska" },
  { wartosc: "lokalna", etykieta: "Lokalna" },
];

function liczba(v: number | null | undefined, cyfry = 0): string {
  if (v === null || v === undefined) return "-";
  return polonizeDecimals(v.toFixed(cyfry)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

function procent(v: number): string {
  return polonizeDecimals((v * 100).toFixed(1)) + "%";
}

/** Pasek udziału formatu - ta sama wizualizacja co w raporcie PDF.
 *
 * Na telefonie etykiety idą nad pasek: trzy kolumny o stałej szerokości zostawiały mu
 * 33 px z 375 px ekranu, czyli tyle, że nie dało się odczytać proporcji.
 */
function PasekUdzialu({ f, moj }: { f: Format; moj?: number }) {
  const tor = (
    <div className="h-2 overflow-hidden rounded-full bg-surface-2">
      <div
        className={`h-full rounded-full ${KOLORY_FORMATOW[f.media_type] ?? "bg-slate-400"}`}
        style={{ width: `${Math.max(2, f.udzial * 100)}%` }}
      />
    </div>
  );
  return (
    <div className="sm:flex sm:items-center sm:gap-3">
      <div className="flex items-baseline justify-between gap-2 sm:contents">
        <span className="text-sm text-text sm:w-20 sm:shrink-0">
          {NAZWY_FORMATOW[f.media_type] ?? f.media_type}
        </span>
        <span className="sm:hidden">
          <span className="tabnum text-sm font-medium text-text">{procent(f.udzial)}</span>
          {moj !== undefined && (
            <span className="tabnum ml-2 text-xs text-text-subtle">u Ciebie {procent(moj)}</span>
          )}
        </span>
      </div>
      <div className="mt-1.5 sm:mt-0 sm:min-w-0 sm:flex-1">{tor}</div>
      <span className="tabnum hidden w-14 shrink-0 text-right text-sm font-medium text-text sm:inline">
        {procent(f.udzial)}
      </span>
      <span className="tabnum hidden w-24 shrink-0 text-right text-xs text-text-subtle sm:inline">
        {moj !== undefined ? `u Ciebie ${procent(moj)}` : "-"}
      </span>
    </div>
  );
}

/** Co widać / czego nie widać - obowiązkowy element każdej grupy (decyzja #22). */
function RamkaWidocznosci({ g }: { g: GrupaRaport }) {
  return (
    <div className="grid gap-4 rounded-lg border border-border bg-surface-2 p-4 sm:grid-cols-2">
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-success">
          <Eye className="h-3.5 w-3.5" /> Co widać publicznie
        </p>
        <ul className="space-y-1">
          {g.widoczne.map((w) => (
            <li key={w} className="text-xs text-text-muted">
              <span className="text-success">■</span> {w}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-danger">
          <EyeOff className="h-3.5 w-3.5" /> Czego nie widać
        </p>
        <ul className="space-y-1">
          {g.niewidoczne.map((w) => (
            <li key={w} className="text-xs text-text-muted">
              <span className="text-danger">■</span> {w}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function SekcjaGrupy({
  g,
  wlasne,
  onUsun,
}: {
  g: GrupaRaport;
  wlasne: Record<string, number>;
  onUsun: (k: ProfilWRaporcie) => void;
}) {
  const rozjazd =
    g.mediana_zaangazowania && g.srednia_zaangazowania
      ? g.srednia_zaangazowania > g.mediana_zaangazowania * 1.5
      : false;

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-text">{g.nazwa}</h3>
          <p className="mt-0.5 text-sm text-text-muted">
            {g.profili === 0
              ? "Brak obserwowanych konkurentów w tej grupie."
              : g.dosc_danych
                ? `${g.profili} obserwowanych · ${g.postow} postów · ${liczba(g.postow_na_tydzien, 1)} posta/tydzień · mediana zaangażowania ${liczba(g.mediana_zaangazowania, 1)}`
                : `${g.profili} obserwowanych, ale tylko ${g.postow} postów - za mało na wskaźniki (próg: ${g.min_postow}).`}
          </p>
        </div>
        {g.dosc_danych && <Badge tone="success">dość danych</Badge>}
      </div>

      {g.profili > 0 && (
        <>
          <RamkaWidocznosci g={g} />

          <Table>
            <THead>
              <Tr>
                <Th>Konkurent</Th>
                <Th>Instagram</Th>
                <Th align="right">Obserwujący</Th>
                <Th align="right">Zmiana 30 dni</Th>
                {/* „Zebranych łącznie", nie „postów" - to CAŁA historia profilu, a liczba
                    w podsumowaniu grupy dotyczy tylko wybranego okresu. Ta sama etykieta
                    dla dwóch różnych liczb wyglądałaby jak błąd. */}
                <Th align="right">Zebranych łącznie</Th>
                <Th align="right"> </Th>
              </Tr>
            </THead>
            <TBody>
              {g.profile.map((p) => (
                <Tr key={p.id}>
                  <Td>{p.name}</Td>
                  <Td>
                    {p.ig_username ? (
                      <span className="text-text-muted">@{p.ig_username}</span>
                    ) : (
                      <span className="text-text-subtle">-</span>
                    )}
                  </Td>
                  <Td align="right">{liczba(p.followers)}</Td>
                  <Td align="right">
                    {p.przyrost_30d_pct === null ? (
                      <span className="text-text-subtle">-</span>
                    ) : (
                      <span
                        className={
                          p.przyrost_30d_pct > 0
                            ? "font-medium text-success"
                            : p.przyrost_30d_pct < 0
                              ? "font-medium text-danger"
                              : "text-text-muted"
                        }
                      >
                        {p.przyrost_30d_pct > 0 ? "+" : ""}
                        {liczba(p.przyrost_30d_pct, 1)}%
                      </span>
                    )}
                  </Td>
                  <Td align="right">{liczba(p.postow_zebranych)}</Td>
                  <Td align="right">
                    <button
                      type="button"
                      onClick={() => onUsun(p)}
                      aria-label={`Usuń konkurenta ${p.name}`}
                      className="rounded p-1 text-text-subtle hover:bg-surface-2 hover:text-danger"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </>
      )}

      {g.dosc_danych && (
        <>
          <div className="space-y-2">
            <p className="text-sm font-medium text-text">Rozkład formatów - grupa kontra Twój profil</p>
            {g.formaty.map((f) => (
              <PasekUdzialu key={f.media_type} f={f} moj={wlasne[f.media_type]} />
            ))}
          </div>

          {rozjazd && (
            <p className="rounded-lg bg-warning-soft px-3 py-2 text-xs text-text-muted">
              <span className="text-orange-500">■</span> Średnia zaangażowania (
              {liczba(g.srednia_zaangazowania, 1)}) jest znacznie wyższa od mediany (
              {liczba(g.mediana_zaangazowania, 1)}) - grupę ciągnie kilka wyjątkowych postów, a nie
              stały poziom.
            </p>
          )}

          <div className="space-y-2">
            <p className="text-sm font-medium text-text">Najmocniejsze posty okresu</p>
            <div className="space-y-2">
              {g.top_posty.map((p, i) => (
                <div
                  key={`${p.profil}-${i}`}
                  className="flex items-start gap-3 rounded-lg border border-border p-3"
                >
                  <Badge tone="neutral">{NAZWY_FORMATOW[p.media_type] ?? p.media_type}</Badge>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-text">{p.profil}</p>
                    <p className="mt-0.5 line-clamp-2 text-xs text-text-muted">{p.caption || "-"}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="tabnum text-sm font-semibold text-text">{liczba(p.engagement)}</p>
                    <p className="text-xs text-text-subtle">lajki + kom.</p>
                  </div>
                  {p.permalink && (
                    <a
                      href={p.permalink}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="shrink-0 text-xs text-primary hover:underline"
                    >
                      otwórz
                    </a>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

function FormularzKonkurenta({ onDodano }: { onDodano: () => void }) {
  const toast = useToast();
  const [grupa, setGrupa] = useState<Grupa>("polska");
  const [name, setName] = useState("");
  const [ig, setIg] = useState("");
  const [www, setWww] = useState("");

  const dodaj = useMutation({
    mutationFn: () =>
      api.post<Konkurent>("/konkurencja", {
        grupa,
        name: name.trim(),
        // Małpa bywa wklejana razem z loginem - obcinamy, bo API oczekuje samej nazwy.
        ig_username: ig.trim().replace(/^@/, "") || null,
        www: www.trim() || null,
      }),
    onSuccess: () => {
      setName("");
      setIg("");
      setWww("");
      toast.success("Dodano konkurenta.");
      onDodano();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Nie udało się dodać."),
  });

  return (
    <Card className="space-y-3 p-5">
      <p className="text-sm font-medium text-text">Dodaj konkurenta</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <Label htmlFor="k-grupa">Grupa</Label>
          <Select id="k-grupa" value={grupa} onChange={(e) => setGrupa(e.target.value as Grupa)}>
            {GRUPY.map((g) => (
              <option key={g.wartosc} value={g.wartosc}>
                {g.etykieta}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="k-nazwa">Nazwa firmy</Label>
          <Input
            id="k-nazwa"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="np. Sklep Rowerowy Przykład"
          />
        </div>
        <div>
          <Label htmlFor="k-ig">Instagram (opcjonalnie)</Label>
          <Input
            id="k-ig"
            value={ig}
            onChange={(e) => setIg(e.target.value)}
            placeholder="@nazwa_konta"
          />
        </div>
        <div>
          <Label htmlFor="k-www">Strona (opcjonalnie)</Label>
          <Input
            id="k-www"
            value={www}
            onChange={(e) => setWww(e.target.value)}
            placeholder="https://…"
          />
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={() => dodaj.mutate()} disabled={!name.trim() || dodaj.isPending}>
          <Plus className="h-4 w-4" /> Dodaj
        </Button>
        <p className="text-xs text-text-subtle">
          Konto Instagrama pozwala pobierać dane automatycznie - działa tylko dla publicznych kont
          firmowych (Business/Creator).
        </p>
      </div>
    </Card>
  );
}

export function Competitors() {
  const qc = useQueryClient();
  const toast = useToast();
  const dr = useDateRange();
  const [doUsuniecia, setDoUsuniecia] = useState<ProfilWRaporcie | null>(null);

  const raport = useQuery({
    queryKey: ["konkurencja", dr.from, dr.to],
    queryFn: () => api.get<Raport>(`/konkurencja/raport${dr.query}`),
  });

  const usun = useMutation({
    mutationFn: (id: number) => api.delete(`/konkurencja/${id}`),
    onSuccess: () => {
      setDoUsuniecia(null);
      qc.invalidateQueries({ queryKey: ["konkurencja"] });
      toast.success("Usunięto konkurenta wraz z obserwacjami.");
    },
    onError: () => toast.error("Nie udało się usunąć."),
  });

  const sync = useMutation({
    mutationFn: () => api.post<{ status: string }>("/konkurencja/sync"),
    onSuccess: () =>
      toast.success("Zlecono pobranie danych. Bez skonfigurowanego konta Meta zadanie zostanie pominięte."),
    onError: () => toast.error("Nie udało się zlecić pobrania."),
  });

  const wlasneUdzialy: Record<string, number> = {};
  for (const f of raport.data?.wlasny.formaty ?? []) wlasneUdzialy[f.media_type] = f.udzial;

  const pusto = raport.data && raport.data.profili_lacznie === 0;

  return (
    <div className="space-y-5">
      <PageHead
        title="Konkurencja"
        subtitle="Trzy grupy, wyłącznie dane publiczne. Zasięgu i wydatków konkurencji nie widać."
        actions={
          <>
            <Button variant="secondary" onClick={() => sync.mutate()} disabled={sync.isPending}>
              <RefreshCw className={`h-4 w-4 ${sync.isPending ? "animate-spin" : ""}`} /> Pobierz z IG
            </Button>
            <a href={`/api/reports/konkurencja.pdf?download=true${dr.query.replace("?", "&")}`}>
              <Button variant="secondary">
                <Download className="h-4 w-4" /> Raport PDF
              </Button>
            </a>
          </>
        }
      />

      <FormularzKonkurenta onDodano={() => qc.invalidateQueries({ queryKey: ["konkurencja"] })} />

      {raport.isLoading && (
        <div className="space-y-4">
          <Skeleton className="h-56 w-full rounded-xl" />
          <Skeleton className="h-56 w-full rounded-xl" />
        </div>
      )}

      {pusto && (
        <EmptyState
          icon={Eye}
          title="Nie obserwujesz jeszcze nikogo"
          description="Dodaj konkurentów powyżej i przypisz ich do grup: europejskiej, polskiej i lokalnej."
        />
      )}

      {raport.data &&
        !pusto &&
        raport.data.grupy.map((g) => (
          <SekcjaGrupy key={g.grupa} g={g} wlasne={wlasneUdzialy} onUsun={setDoUsuniecia} />
        ))}

      <ConfirmDialog
        open={doUsuniecia !== null}
        title="Usunąć konkurenta?"
        message={
          <>
            <span className="font-medium text-text">{doUsuniecia?.name}</span> zniknie z listy wraz ze
            wszystkimi zebranymi obserwacjami ({liczba(doUsuniecia?.postow_zebranych ?? 0)} postów).
            Tej operacji nie można cofnąć.
          </>
        }
        confirmLabel="Usuń"
        cancelLabel="Anuluj"
        danger
        busy={usun.isPending}
        onConfirm={() => {
          if (doUsuniecia) usun.mutate(doUsuniecia.id);
        }}
        onCancel={() => setDoUsuniecia(null)}
      />
    </div>
  );
}
