"""Public support knowledge base endpoints."""

from html import escape
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from automail.db.pocketbase.client import (
    get_public_knowledge_article,
    list_public_knowledge_articles,
)

router = APIRouter()


def _clean_limit(limit: int) -> int:
    return max(1, min(limit, 100))


@router.get("/api/support/knowledge/{project_id}")
async def get_public_knowledge(
    project_id: str,
    tenant_id: str | None = None,
    q: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    return {
        "items": list_public_knowledge_articles(
            tenant_id=tenant_id,
            project_id=project_id,
            query=q,
            limit=_clean_limit(limit),
        )
    }


@router.get("/api/support/knowledge/{project_id}/articles/{article_id}")
async def get_public_article(
    project_id: str,
    article_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    article = get_public_knowledge_article(
        article_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


def _project_path(project_id: str) -> str:
    return f"/support/knowledge/{quote(project_id, safe='')}"


def _article_path(project_id: str, article_id: str) -> str:
    return f"{_project_path(project_id)}/articles/{quote(article_id, safe='')}"


def _query_path(project_id: str, query: str) -> str:
    if not query.strip():
        return _project_path(project_id)
    return f"{_project_path(project_id)}?{urlencode({'q': query.strip()})}"


def _page_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f8fafc; color: #111827; }}
    main {{ max-width: 920px; margin: 0 auto; padding: 32px 20px; }}
    header {{ margin-bottom: 24px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; line-height: 1.2; }}
    h2 {{ margin: 0 0 8px; font-size: 18px; line-height: 1.3; }}
    a {{ color: inherit; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .subtle {{ color: #64748b; font-size: 14px; }}
    .panel, .article {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; }}
    .stack {{ display: grid; gap: 12px; }}
    .search {{ display: flex; gap: 8px; margin-top: 16px; }}
    input {{ flex: 1; min-width: 0; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px; font: inherit; }}
    button {{ border: 0; border-radius: 6px; background: #111827; color: white; padding: 10px 14px; font: inherit; cursor: pointer; }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
    .tag {{ border: 1px solid #cbd5e1; border-radius: 999px; padding: 2px 8px; font-size: 12px; color: #475569; }}
    pre {{ white-space: pre-wrap; font: inherit; margin: 0; line-height: 1.6; }}
    .back {{ display: inline-flex; margin-bottom: 16px; color: #475569; font-size: 14px; }}
    .empty {{ color: #64748b; padding: 24px 0; }}
  </style>
</head>
<body>
  <main data-public-help-center="true">
    {body}
  </main>
</body>
</html>"""


def _render_article_list(project_id: str, articles: list[dict[str, Any]], query: str) -> str:
    article_html = "\n".join(
        f"""
        <article class="article">
          <a href="{escape(_article_path(project_id, str(article.get('id') or '')))}">
            <h2>{escape(str(article.get('title') or 'Untitled article'))}</h2>
          </a>
          <div class="subtle">{escape(str(article.get('excerpt') or ''))}</div>
          {_render_tags(article.get('tags'))}
        </article>
        """
        for article in articles
    ) or '<div class="empty">No public articles found.</div>'
    body = f"""
      <header>
        <h1>Help center</h1>
        <div class="subtle">Search published support articles.</div>
        <form class="search" method="get" action="{escape(_project_path(project_id))}">
          <input name="q" value="{escape(query)}" placeholder="Search articles" />
          <button type="submit">Search</button>
        </form>
      </header>
      <section class="stack">{article_html}</section>
    """
    return _page_shell("Help center", body)


def _render_tags(tags: Any) -> str:
    if not isinstance(tags, list) or not tags:
        return ""
    tag_html = "".join(f'<span class="tag">{escape(str(tag))}</span>' for tag in tags if str(tag).strip())
    return f'<div class="tags">{tag_html}</div>' if tag_html else ""


def _render_article(project_id: str, article: dict[str, Any], query: str) -> str:
    back_path = _query_path(project_id, query)
    body = f"""
      <a class="back" href="{escape(back_path)}">Back to help center</a>
      <article class="panel">
        <h1>{escape(str(article.get('title') or 'Untitled article'))}</h1>
        <div class="subtle">Updated {escape(str(article.get('updated') or ''))}</div>
        {_render_tags(article.get('tags'))}
        <div style="margin-top:20px">
          <pre>{escape(str(article.get('body') or ''))}</pre>
        </div>
      </article>
    """
    return _page_shell(str(article.get("title") or "Help article"), body)


@router.get("/support/knowledge/{project_id}", response_class=HTMLResponse)
async def get_public_knowledge_page(
    project_id: str,
    tenant_id: str | None = None,
    q: str = "",
    limit: int = 50,
) -> HTMLResponse:
    articles = list_public_knowledge_articles(
        tenant_id=tenant_id,
        project_id=project_id,
        query=q,
        limit=_clean_limit(limit),
    )
    return HTMLResponse(_render_article_list(project_id, articles, q))


@router.get("/support/knowledge/{project_id}/articles/{article_id}", response_class=HTMLResponse)
async def get_public_article_page(
    project_id: str,
    article_id: str,
    tenant_id: str | None = None,
    q: str = "",
) -> HTMLResponse:
    article = get_public_knowledge_article(
        article_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return HTMLResponse(_render_article(project_id, article, q))
