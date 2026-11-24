"""Literal search over prepared paragraph text, one chapter at a time."""
from __future__ import annotations

import json
import re

from . import library


def search_book(book_id: str, query: str, scope: str = "book", chapter: int = 0,
                offset: int = 0, limit: int = 100) -> dict:
    query = " ".join(query.split())
    if not query:
        raise ValueError("Введите текст для поиска")
    if len(query) > 160:
        raise ValueError("Поисковый запрос не должен превышать 160 символов")
    if scope not in {"book", "chapter"}:
        raise ValueError("Неизвестная область поиска")
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("Неверная страница результатов поиска")
    book = library.get_book(book_id)
    if book.get("reader_type") == "pages" or str(book.get("format", "")).lower() in {"pdf", "cbz", "cbr"}:
        raise ValueError("Поиск по тексту недоступен для PDF и комиксов: распознавание текста пока не поддерживается")
    count = book["chapter_count"]
    if scope == "chapter" and not 0 <= chapter < count:
        raise KeyError("Раздел не найден")
    indices = [chapter] if scope == "chapter" else range(count)
    directory = library._book_dir(book_id) / "chapters"
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    total, results = 0, []
    for index in indices:
        with (directory / f"{index}.json").open(encoding="utf-8") as source:
            data = json.load(source)
        title = data.get("title") or f"Раздел {index + 1}"
        for paragraph in data.get("paragraphs", []):
            # This is the same whitespace canonicalization used by the importer.
            text = " ".join(paragraph.get("text", "").split())
            for match in pattern.finditer(text):
                if offset <= total < offset + limit:
                    start, end = match.span()
                    results.append({
                        "chapter": index, "chapter_title": title, "id": paragraph["id"],
                        "start": len(text[:start].encode("utf-16-le", errors="surrogatepass")) // 2,
                        "end": len(text[:end].encode("utf-16-le", errors="surrogatepass")) // 2,
                        "before": text[max(0, start - 70):start], "match": match.group(),
                        "after": text[end:end + 70],
                    })
                total += 1
        # Release the chapter's HTML and paragraph collection before opening the next.
        del data
    next_offset = offset + len(results) if offset + len(results) < total else None
    return {"query": query, "scope": scope, "total": total, "offset": offset,
            "next_offset": next_offset, "results": results}
