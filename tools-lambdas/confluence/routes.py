"""Confluence mock routes ported from mahalo-dock confluence/main.py.

Collections (``pk``): SPACE, PAGE (natural id under ``sk``; record under ``data``).
"""

from common.auth import require_token
from common.responses import error, json_response
from common.router import Router

from . import seed_data

PK_SPACE = "SPACE"
PK_PAGE = "PAGE"


def seed_items():
    for space in seed_data.SPACES:
        yield {"pk": PK_SPACE, "sk": space["id"], "record": space}
    for page in seed_data.PAGES:
        yield {"pk": PK_PAGE, "sk": page["id"], "record": page}


def _summary(page):
    return {
        "id": page["id"],
        "title": page["title"],
        "author": page["author"],
        "last_updated": page["last_updated"],
        "space_id": page["space_id"],
    }


def build_router(store, token):
    router = Router()

    def _auth(request):
        if not require_token(request, token):
            return error(401, "Invalid API token")
        return None

    @router.route("GET", "/health")
    def health(request):
        return json_response(
            200, {"status": "healthy", "service": "mock-confluence", "version": "1.0.0"}
        )

    # --- Spaces ---

    @router.route("POST", "/spaces")
    def create_space(request):
        denied = _auth(request)
        if denied:
            return denied
        space = request.json_body or {}
        space_id = str(space.get("id") or "SPACE").upper()
        if store.exists(PK_SPACE, space_id):
            return error(409, "Space already exists")
        new_space = {
            "id": space_id,
            "name": space.get("name") or space_id,
            "description": space.get("description") or "",
        }
        store.put(PK_SPACE, space_id, new_space)
        return json_response(201, new_space)

    @router.route("GET", "/spaces")
    def list_spaces(request):
        denied = _auth(request)
        if denied:
            return denied
        return json_response(200, {"spaces": store.query(PK_SPACE)})

    @router.route("GET", "/spaces/{space_id}")
    def get_space(request):
        denied = _auth(request)
        if denied:
            return denied
        space = store.get(PK_SPACE, request.path_params["space_id"])
        if not space:
            return error(404, "Space not found")
        return json_response(200, space)

    @router.route("GET", "/pages")
    def list_all_pages(request):
        denied = _auth(request)
        if denied:
            return denied
        space_id = request.query.get("space_id")
        pages = [
            _summary(p)
            for p in store.query(PK_PAGE)
            if not space_id or p["space_id"] == space_id
        ]
        return json_response(200, {"pages": pages, "total": len(pages)})

    @router.route("GET", "/spaces/{space_id}/pages")
    def list_pages(request):
        denied = _auth(request)
        if denied:
            return denied
        space_id = request.path_params["space_id"]
        pages = [_summary(p) for p in store.query(PK_PAGE) if p["space_id"] == space_id]
        return json_response(200, {"pages": pages, "total": len(pages)})

    @router.route("POST", "/spaces/{space_id}/pages")
    def create_page(request):
        denied = _auth(request)
        if denied:
            return denied
        space_id = request.path_params["space_id"]
        if not store.exists(PK_SPACE, space_id):
            return error(404, "Space not found")
        page = request.json_body or {}
        page_id = str(
            page.get("id") or f"{space_id}-{store.count(PK_PAGE) + 1:03d}"
        ).upper()
        new_page = {
            "id": page_id,
            "space_id": space_id,
            "title": page.get("title") or "New page",
            "author": page.get("author") or "System",
            "last_updated": page.get("last_updated") or "2026-08-29",
            "content": page.get("content") or "",
        }
        store.put(PK_PAGE, page_id, new_page)
        return json_response(201, new_page)

    # --- Pages ---

    @router.route("GET", "/pages/{page_id}")
    def get_page(request):
        denied = _auth(request)
        if denied:
            return denied
        page = store.get(PK_PAGE, request.path_params["page_id"])
        if not page:
            return error(404, "Page not found")
        return json_response(200, page)

    # --- Search ---

    @router.route("GET", "/search")
    def search_pages(request):
        denied = _auth(request)
        if denied:
            return denied
        q = request.query.get("q")
        if not q:
            return error(422, "Field 'q' is required")
        space_id = request.query.get("space_id")
        query_lower = q.lower()
        results = []
        for page in store.query(PK_PAGE):
            if space_id and page["space_id"] != space_id:
                continue
            title_match = query_lower in page["title"].lower()
            content_match = query_lower in page["content"].lower()
            if title_match or content_match:
                if content_match:
                    content_lower = page["content"].lower()
                    idx = content_lower.find(query_lower)
                    start = max(0, idx - 100)
                    end = min(len(page["content"]), idx + len(q) + 100)
                    excerpt = "..." + page["content"][start:end] + "..."
                else:
                    excerpt = page["content"][:200] + "..."
                results.append(
                    {
                        "id": page["id"],
                        "title": page["title"],
                        "space_id": page["space_id"],
                        "author": page["author"],
                        "last_updated": page["last_updated"],
                        "excerpt": excerpt,
                        "relevance": 1.0 if title_match else 0.7,
                    }
                )
        results.sort(key=lambda x: x["relevance"], reverse=True)
        return json_response(200, {"results": results, "total": len(results), "query": q})

    return router
