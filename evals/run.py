"""Ewaluacja asystenta PolSales (opis, metryki i wyniki: evals/README.md).

    cd backend
    python ../evals/run.py --mock                                # atrapa: bez sieci i bez kosztów
    python ../evals/run.py --estimate --model claude-haiku-4-5   # szacunek kosztu prawdziwego przebiegu
    python ../evals/run.py --model claude-haiku-4-5 --yes        # prawdziwe API, kosztuje

Baza: zmienna EVAL_DATABASE_URL albo --database-url. Musi to być osobna baza: skrypt sam uruchamia
na niej migracje i seed_demo, a odmawia pracy, gdy znajdzie w niej dane spoza demo. Klucz AI
bierze się wyłącznie ze zmiennych środowiskowych (OPENROUTER_API_KEY albo ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent

# Odpowiedź modelu z tabelą i komentarzem to zwykle 200-400 tokenów; atrapa pisze krócej,
# więc szacunek przyjmuje 400 tokenów wyjścia na każde wywołanie modelu.
ASSUMED_OUTPUT_TOKENS_PER_CALL = 400


def _estimate(harness, run: dict, model: str) -> dict:
    key, price = harness.price_for(model)
    calls = sum(r["model_calls"] for r in run["results"])
    usage = {"input_tokens": run["summary"]["input_tokens"],
             "output_tokens": calls * ASSUMED_OUTPUT_TOKENS_PER_CALL,
             "cache_read_tokens": 0, "cache_write_tokens": 0}
    return {"price_model": key, "known_price": price is not None, "model_calls": calls, **usage,
            "cost_usd_upper_bound": harness.cost_usd(usage, price)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ewaluacja asystenta PolSales na danych demo.")
    parser.add_argument("--mock", action="store_true", help="atrapa modelu, bez sieci i bez kosztów")
    parser.add_argument("--estimate", action="store_true", help="szacunek kosztu przebiegu na --model (atrapa)")
    parser.add_argument("--model", help="identyfikator modelu (domyślnie CHAT_MODEL z ustawień)")
    parser.add_argument("--yes", action="store_true", help="zgoda na płatny przebieg na prawdziwym API")
    parser.add_argument("--database-url", default=os.environ.get("EVAL_DATABASE_URL"))
    parser.add_argument("--cases", help="tylko wybrane przypadki po początku id, np. 01,07,P3")
    parser.add_argument("--out", help="folder na wynik (domyślnie evals/results dla prawdziwego modelu)")
    parser.add_argument("--no-prepare", action="store_true", help="bez migracji i seed_demo")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not args.database_url:
        parser.error("podaj --database-url albo ustaw EVAL_DATABASE_URL (osobna baza tylko na dane demo)")
    # Ustawienia aplikacji czytają DATABASE_URL przy imporcie, więc najpierw adres bazy ewaluacji.
    os.environ["DATABASE_URL"] = args.database_url
    sys.path.insert(0, str(EVALS_DIR))
    import harness

    from app.ai.client import ai_configured, build_client, resolve_model
    from app.config import settings

    model = args.model or settings.chat_model
    only = args.cases.split(",") if args.cases else None
    common = {"only": only, "prepare": not args.no_prepare}

    if args.mock or args.estimate:
        mock = harness.MockModel()
        run = harness.run_eval(args.database_url, client=mock, mock=mock, model=model, **common)
        if args.estimate:
            print(json.dumps(_estimate(harness, run, model), ensure_ascii=False, indent=2))
            return 0
        print(harness.report_markdown(run))
        if args.out:
            _save(run, Path(args.out), harness)
        s = run["summary"]
        clean = (s["tool_choice"]["ok"] == s["tool_choice"]["of"] and s["numbers"]["ok"] == s["numbers"]["of"]
                 and s["traps"]["ok"] == s["traps"]["of"] and not s["errors"])
        return 0 if clean else 1  # na atrapie każdy przypadek ma przejść

    if not ai_configured():
        print("Brak klucza AI w zmiennych środowiskowych (OPENROUTER_API_KEY albo ANTHROPIC_API_KEY).")
        return 2
    if not args.yes:
        mock = harness.MockModel()
        est = _estimate(harness, harness.run_eval(args.database_url, client=mock, mock=mock, model=model,
                                                  **common), model)
        print(json.dumps(est, ensure_ascii=False, indent=2))
        print("To płatny przebieg. Uruchom ponownie z --yes, jeśli koszt jest w porządku.")
        return 1
    settings.chat_model = model
    run = harness.run_eval(args.database_url, client=build_client(), model=resolve_model(model), **common)
    print(harness.report_markdown(run))
    _save(run, Path(args.out) if args.out else EVALS_DIR / "results", harness)
    return 0


def _save(run: dict, folder: Path, harness) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{run['date']}_{run['model'].replace('/', '_')}"
    (folder / f"{stem}.json").write_text(json.dumps(run, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (folder / f"{stem}.md").write_text(harness.report_markdown(run), encoding="utf-8")
    print(f"Zapisano {folder / stem}.json i .md")


if __name__ == "__main__":
    raise SystemExit(main())
