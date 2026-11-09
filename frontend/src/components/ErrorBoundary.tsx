import * as React from "react";

/** Łapie błędy renderowania React i pokazuje przyjazny ekran zamiast białej strony. */
export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("Błąd interfejsu:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 p-8 text-center">
          <p className="text-lg font-semibold">Coś poszło nie tak</p>
          <p className="max-w-md text-sm text-text-muted">
            Wystąpił nieoczekiwany błąd interfejsu. Odśwież stronę; jeśli problem się powtarza, sprawdź, czy API działa.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="inline-flex h-10 items-center gap-2 rounded-lg bg-[#4F46E5] px-4 text-sm font-medium text-white transition-colors hover:bg-[#4338CA]"
          >
            Odśwież stronę
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
