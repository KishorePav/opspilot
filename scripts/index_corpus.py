from __future__ import annotations

import json
from pathlib import Path

from opspilot.adapters.postgres import PostgresHybridRetriever
from opspilot.bootstrap import build_embedding_provider
from opspilot.config import Settings
from opspilot.corpus import load_markdown_documents
from opspilot.storage.migrations import apply_migrations


def main() -> None:
    settings = Settings.from_environment()
    migrations = apply_migrations(settings.database_url, Path("migrations"))
    documents = load_markdown_documents(settings.corpus_dir)
    if not documents:
        raise SystemExit(f"no Markdown documents found in {settings.corpus_dir}")

    with PostgresHybridRetriever(
        settings.database_url,
        build_embedding_provider(settings),
        pool_min_size=settings.database_pool_min_size,
        pool_max_size=settings.database_pool_max_size,
    ) as retriever:
        indexed_chunks = retriever.index_documents(documents)

    print(
        json.dumps(
            {
                "documents": len(documents),
                "indexed_chunks": indexed_chunks,
                "migrations_applied": list(migrations.applied),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
