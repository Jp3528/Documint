"""Evaluate lexical/vector/hybrid on the checked corpus; REAL mode must be explicit."""

import argparse
from pathlib import Path

from sqlalchemy.orm import Session

from evals.retrieval import EvaluationError, evaluate_retrieval
from evals.schema import GoldenDataset
from packages.config import get_settings
from packages.database import make_engine
from packages.providers.factory import make_embedding_provider
from scripts.seed_corpus import ROOT, demo_manifest
from scripts.seed_demo import demo_personas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["FAKE", "REAL"], required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    provider = make_embedding_provider(settings)
    if provider.model.mode != args.mode:
        parser.error("mode must match the configured actual provider; no fake fallback")
    engine = make_engine(settings)
    try:
        with Session(engine, expire_on_commit=False) as db:
            golden = GoldenDataset.model_validate_json(
                (ROOT / "evals/golden.json").read_text("utf-8")
            )
            try:
                report = evaluate_retrieval(
                    db, provider, args.mode, demo_manifest(), demo_personas(), golden, args.top_k
                )
            except EvaluationError as exc:
                parser.error(str(exc))
        output = args.output or ROOT / f"evals/reports/retrieval_{args.mode.lower()}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"{report.status}: mode={report.mode}; {len(report.cases)} method/case observations")
        print(f"Observed query provider requests: {report.query_provider_calls}; report: {output}")
        if any(
            row.unauthorized_hits or row.forbidden_hits or row.error_code for row in report.cases
        ):
            raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
