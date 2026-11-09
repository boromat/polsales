// Rekomendacje AI - karty z feedbackiem i generowaniem na żądanie. Etap 5.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Sparkles, ThumbsDown, ThumbsUp, X } from "lucide-react";

import { polonizeDecimals } from "@/lib/format";
import { api } from "@/api/client";
import { Badge, Button, Card, ConfirmDialog, EmptyState, PageHead, Skeleton } from "@/components/ui";
import { useToast } from "@/components/toast";

interface Rec {
  id: string;
  created_at: string;
  category: string;
  title: string;
  body: string;
  supporting_metrics: unknown;
  confidence: string;
  feedback: string | null;
  model: string | null;
}

const CATEGORY_LABEL: Record<string, string> = {
  content_format: "Treści organiczne",
  ad_creative: "Kreacje reklam",
  budget_allocation: "Budżet",
  timing: "Czas publikacji",
  product: "Produkty",
};

const CONFIDENCE_TONE: Record<string, "success" | "warning" | "neutral"> = {
  high: "success",
  medium: "warning",
  low: "neutral",
};

export function Recommendations() {
  const qc = useQueryClient();
  const toast = useToast();
  const recs = useQuery({ queryKey: ["recs"], queryFn: () => api.get<Rec[]>("/recommendations?status=active") });

  // Rekomendacja oczekująca na potwierdzenie archiwizacji (null = dialog zamknięty).
  const [pendingDismiss, setPendingDismiss] = useState<Rec | null>(null);

  const generate = useMutation({
    mutationFn: () => api.post<{ inserted: number; method: string }>("/recommendations/generate"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recs"] }),
  });
  const feedback = useMutation({
    mutationFn: ({ id, value }: { id: string; value: string }) =>
      api.post(`/recommendations/${id}/feedback`, { feedback: value }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recs"] });
      toast.success("Zapisano opinię.");
    },
    onError: () => toast.error("Nie udało się zapisać opinii."),
  });
  const dismiss = useMutation({
    mutationFn: (id: string) => api.post(`/recommendations/${id}/dismiss`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recs"] });
      toast.success("Rekomendacja została zarchiwizowana.");
      setPendingDismiss(null);
    },
    onError: () => toast.error("Nie udało się zarchiwizować rekomendacji."),
  });

  const generateBtn = (
    <Button variant="secondary" onClick={() => generate.mutate()} disabled={generate.isPending}>
      <RefreshCw className={`h-4 w-4 ${generate.isPending ? "animate-spin" : ""}`} /> Generuj teraz
    </Button>
  );

  return (
    <div className="space-y-6">
      <PageHead
        subtitle="Rekomendacje z analizy skuteczności. Generowane co noc o 5:00 oraz na żądanie."
        actions={generateBtn}
      />

      {generate.data && (
        <div className="flex items-center gap-2 rounded-lg border border-success/30 bg-success-soft px-4 py-2.5 text-sm text-success animate-fade-in">
          <Sparkles className="h-4 w-4 shrink-0" />
          <span>
            Wygenerowano {generate.data.inserted} nowych rekomendacji ({generate.data.method === "ai" ? "AI" : "reguły"}).
          </span>
        </div>
      )}

      {recs.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i} className="p-4">
              <div className="flex items-center gap-2">
                <Skeleton className="h-5 w-28 rounded-full" />
                <Skeleton className="h-5 w-24 rounded-full" />
              </div>
              <Skeleton className="mt-3 h-4 w-1/2" />
              <Skeleton className="mt-2.5 h-3 w-full" />
              <Skeleton className="mt-1.5 h-3 w-4/5" />
              <div className="mt-4 flex gap-2">
                <Skeleton className="h-8 w-20 rounded-lg" />
                <Skeleton className="h-8 w-24 rounded-lg" />
              </div>
            </Card>
          ))}
        </div>
      ) : recs.data && recs.data.length > 0 ? (
        <div className="space-y-3 animate-fade-in">
          {recs.data.map((r) => (
            <Card key={r.id} className="p-4">
              <div className="mb-2.5 flex items-center gap-2">
                <Badge tone="primary">{CATEGORY_LABEL[r.category] ?? r.category}</Badge>
                <Badge tone={CONFIDENCE_TONE[r.confidence] ?? "neutral"} dot>
                  pewność: {r.confidence}
                </Badge>
                <Button
                  variant="ghost"
                  size="icon"
                  className="!h-8 !w-8 ml-auto"
                  onClick={() => setPendingDismiss(r)}
                  title="Archiwizuj"
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
              <h3 className="mb-1 font-semibold text-text">{polonizeDecimals(r.title)}</h3>
              <p className="text-sm leading-relaxed text-text-muted">{polonizeDecimals(r.body)}</p>
              <div className="mt-4 flex items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => feedback.mutate({ id: r.id, value: "trafna" })}
                  className={
                    r.feedback === "trafna"
                      ? "!border-success/30 !bg-success-soft !text-success hover:!bg-success/15"
                      : ""
                  }
                >
                  <ThumbsUp className="h-3.5 w-3.5" /> Trafna
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => feedback.mutate({ id: r.id, value: "nietrafna" })}
                  className={
                    r.feedback === "nietrafna"
                      ? "!border-danger/30 !bg-danger-soft !text-danger hover:!bg-danger/15"
                      : ""
                  }
                >
                  <ThumbsDown className="h-3.5 w-3.5" /> Nietrafna
                </Button>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Sparkles}
          title="Brak aktywnych rekomendacji"
          description="Kliknij „Generuj teraz”, aby przeanalizować dane."
          action={generateBtn}
        />
      )}

      <ConfirmDialog
        open={pendingDismiss !== null}
        title="Zarchiwizować rekomendację?"
        message={
          <>
            Rekomendacja{" "}
            <span className="font-medium text-text">„{polonizeDecimals(pendingDismiss?.title)}”</span>{" "}
            zniknie z listy aktywnych. Tej operacji nie można cofnąć.
          </>
        }
        confirmLabel="Archiwizuj"
        cancelLabel="Anuluj"
        danger
        busy={dismiss.isPending}
        onConfirm={() => {
          if (pendingDismiss) dismiss.mutate(pendingDismiss.id);
        }}
        onCancel={() => setPendingDismiss(null)}
      />
    </div>
  );
}
