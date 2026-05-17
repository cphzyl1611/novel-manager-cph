"""Create Legado BookSource API files."""
import os

ROOT = r"E:\github\novel_repo_manager"

with open(os.path.join(ROOT, "novel_manager", "server", "services", "legado_service.py"), "w", encoding="utf-8") as f:
    f.write('''"""Legado BookSource adapter."""
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
''')
print("legado_service.py done")

with open(os.path.join(ROOT, "novel_manager", "server", "api", "legado.py"), "w", encoding="utf-8") as f:
    f.write('''"""Legado BookSource API endpoints."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query, Request
from ..services.legado_service import book_info, build_source_json, get_content, get_toc, search_books

router = APIRouter(prefix="/api/legado", tags=["legado"])

@router.get("/source")
def legado_source(request: Request):
    host = request.client.host if request.client else "localhost:8765"
    return build_source_json(host)

@router.post("/search")
def legado_search(request: Request, key: str = Query(default=""), page: int = Query(default=1, ge=1)):
    return search_books(request.app.state.repo_path, key=key, page=page)

@router.get("/book/{book_id}")
def legado_book_info(request: Request, book_id: int):
    r = book_info(request.app.state.repo_path, book_id)
    if r is None: raise HTTPException(status_code=404, detail="Book not found")
    return r

@router.get("/book/{book_id}/chapters")
def legado_toc(request: Request, book_id: int):
    r = get_toc(request.app.state.repo_path, book_id)
    if r is None: raise HTTPException(status_code=404, detail="Book not found")
    return r

@router.get("/book/{book_id}/chapter/{chapter_index}")
def legado_content(request: Request, book_id: int, chapter_index: int):
    r = get_content(request.app.state.repo_path, book_id, chapter_index)
    if r is None: raise HTTPException(status_code=404, detail="Chapter not found")
    return r
''')
print("legado.py done")

app_py = os.path.join(ROOT, "novel_manager", "server", "app.py")
content = open(app_py, encoding="utf-8").read()
if "legado" not in content:
    content = content.replace(
        "from .api import books, groups, health, incoming, issues, mobile",
        "from .api import books, groups, health, incoming, issues, legado, mobile"
    )
    content = content.replace(
        "app.include_router(mobile.router)",
        "app.include_router(legado.router)\n    app.include_router(mobile.router)"
    )
    open(app_py, "w", encoding="utf-8").write(content)
    print("app.py updated")
else:
    print("app.py already has legado router")
