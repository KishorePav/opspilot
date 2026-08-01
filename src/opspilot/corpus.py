from __future__ import annotations

from pathlib import Path

from opspilot.domain.models import Document


def load_markdown_documents(directory: Path) -> list[Document]:
    documents = []
    for path in sorted(directory.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        title = content.splitlines()[0].lstrip("# ").strip() or path.stem
        documents.append(
            Document(
                document_id=path.stem,
                title=title,
                content=content,
                source=str(path),
                metadata={"environment": "synthetic"},
            )
        )
    return documents
