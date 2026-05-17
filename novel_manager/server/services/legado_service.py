"""Legado BookSource adapter."""
from __future__ import annotations
from .mobile_service import get_mobile_books, get_mobile_chapters, get_mobile_chapter_content

def search_books(repo_path, key="", page=1):
    data = get_mobile_books(repo_path)
    items = data.get("items", [])
    if key:
        kl = key.lower()
        items = [i for i in items if kl in (i.get("title","") + i.get("author","")).lower()]
    ps, start = 20, (page - 1) * 20
    pi = items[start:start + ps]
    return {"items": [{"book_id": str(i["book_id"]), "title": i["title"], "author": i["author"], "chapter_count": str(i["chapter_count"]), "latest_read_at": i.get("latest_read_at") or ""} for i in pi]}

def book_info(repo_path, book_id):
    for i in get_mobile_books(repo_path).get("items", []):
        if i["book_id"] == book_id:
            return {"book_id": str(i["book_id"]), "title": i["title"], "author": i["author"], "chapter_count": str(i.get("chapter_count", 0)), "description": str(i.get("chapter_count",0)) + "章 · NovelHub书库", "latest_read_at": i.get("latest_read_at") or ""}
    return None

def get_toc(repo_path, book_id):
    data = get_mobile_chapters(repo_path, book_id)
    if data is None: return None
    return {"book_id": str(book_id), "title": data.get("title", ""), "chapters": [{"index": str(c["index"]), "title": c.get("title", "Part " + str(c["index"] + 1)), "char_count": str(c.get("char_count", 0))} for c in data.get("chapters", [])]}

def get_content(repo_path, book_id, chapter_index):
    data = get_mobile_chapter_content(repo_path, book_id, chapter_index)
    if data is None: return None
    return {"book_id": str(data["book_id"]), "chapter_index": str(data["chapter_index"]), "title": data.get("title", ""), "content": data.get("content", ""), "encoding": data.get("encoding", "")}

def build_source_json(server_host):
    base = f"http://{server_host}/api/legado"
    return {"bookSourceUrl": base, "bookSourceName": "NovelHub", "bookSourceGroup": "局域网", "bookSourceType": 0, "bookSourceComment": "电脑端 NovelHub 书库", "enabled": True, "ruleSearch": {"searchUrl": f"{base}/search?key={{key}}&page={{page}}", "bookList": "$.items[*]", "name": "$.title", "author": "$.author", "kind": "$.chapter_count", "lastChapter": "$.latest_read_at", "bookUrl": "$.book_id"}, "ruleBookInfo": {"init": "", "name": "$.title", "author": "$.author", "intro": "$.description", "tocUrl": "$.book_id"}, "ruleToc": {"chapterList": "$.chapters[*]", "chapterName": "$.title", "chapterUrl": "$.index"}, "ruleContent": {"content": "$.content"}}
