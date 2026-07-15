"""Public customer support portal endpoints."""

import json
from html import escape
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from automail.db.pocketbase.client import (
    create_customer_portal_feedback,
    create_customer_portal_message,
    get_customer_portal,
)
from automail.models import CamelCaseModel

router = APIRouter()


class PortalMessageCreate(CamelCaseModel):
    body: str
    sender_name: str = ""
    sender_email: str = ""


class PortalFeedbackCreate(CamelCaseModel):
    rating: int
    comment: str = ""
    sender_name: str = ""
    sender_email: str = ""


def _portal_or_404(token: str) -> dict[str, Any]:
    portal = get_customer_portal(token)
    if not portal:
        raise HTTPException(status_code=404, detail="Portal session not found")
    return portal


def _script_json(value: str) -> str:
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


@router.get("/api/support/portal/{token}")
async def get_portal(token: str) -> dict[str, Any]:
    return _portal_or_404(token)


@router.post("/api/support/portal/{token}/messages")
async def add_portal_message(token: str, body: PortalMessageCreate) -> dict[str, Any]:
    try:
        message = create_customer_portal_message(
            token,
            body=body.body,
            sender_name=body.sender_name,
            sender_email=body.sender_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not message:
        raise HTTPException(status_code=404, detail="Portal session not found")
    return message


@router.post("/api/support/portal/{token}/feedback")
async def add_portal_feedback(token: str, body: PortalFeedbackCreate) -> dict[str, Any]:
    try:
        feedback = create_customer_portal_feedback(
            token,
            rating=body.rating,
            comment=body.comment,
            sender_name=body.sender_name,
            sender_email=body.sender_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not feedback:
        raise HTTPException(status_code=404, detail="Portal session not found")
    return feedback


def _render_portal_html(portal: dict[str, Any], token: str) -> str:
    issue = portal.get("issue", {})
    session = portal.get("session", {}) if isinstance(portal.get("session"), dict) else {}
    project_id = str(session.get("projectId") or issue.get("projectId") or "")
    messages = issue.get("messages", [])
    feedback = portal.get("feedback") or {}
    feedback_rating = int(feedback.get("rating") or 0) if isinstance(feedback, dict) else 0
    token_json = _script_json(token)
    project_json = _script_json(project_id)
    help_section = """
    <section class="panel" data-portal-help="true" style="margin-top:16px">
      <div class="meta">Help articles</div>
      <div class="row">
        <input id="helpSearch" placeholder="Search articles" />
        <button id="helpSearchButton" type="button">Search</button>
      </div>
      <div id="helpResults" class="stack" style="margin-top:10px"></div>
      <article id="helpArticle" class="message" style="display:none;margin-top:10px"></article>
    </section>
    """ if project_id else ""
    message_html = "\n".join(
        f"""
        <article class="message {escape(str(message.get('direction', '')))}">
            <div class="meta">{escape(str(message.get('sender') or message.get('direction') or 'Message'))}
            · {escape(str(message.get('occurredAt') or ''))}</div>
            <pre>{escape(str(message.get('body') or ''))}</pre>
        </article>
        """
        for message in messages
    ) or '<div class="empty">No messages yet.</div>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(str(issue.get('subject') or 'Support request'))}</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f8fafc; color: #111827; }}
    main {{ max-width: 820px; margin: 0 auto; padding: 32px 20px; }}
    header {{ margin-bottom: 20px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; line-height: 1.25; }}
    .subtle {{ color: #64748b; font-size: 14px; }}
    .pill {{ display: inline-flex; border: 1px solid #cbd5e1; border-radius: 999px; padding: 3px 9px; font-size: 12px; margin-right: 6px; background: white; }}
    .panel, .message {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; }}
    .stack {{ display: grid; gap: 12px; }}
    .row {{ display: flex; gap: 8px; }}
    .meta {{ color: #64748b; font-size: 12px; margin-bottom: 8px; }}
    pre {{ white-space: pre-wrap; font: inherit; margin: 0; line-height: 1.55; }}
    textarea, input {{ width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px; font: inherit; }}
    label {{ display: block; font-size: 13px; font-weight: 600; margin: 12px 0 6px; }}
    button {{ margin-top: 12px; border: 0; border-radius: 6px; background: #111827; color: white; padding: 10px 14px; font: inherit; cursor: pointer; }}
    .row button {{ margin-top: 0; }}
    .article-button {{ display: block; width: 100%; margin-top: 8px; border: 1px solid #e2e8f0; background: #fff; color: #111827; text-align: left; }}
    .article-title {{ font-weight: 600; }}
    .article-excerpt {{ color: #64748b; font-size: 13px; margin-top: 4px; }}
    button:disabled {{ opacity: .6; cursor: wait; }}
    .empty {{ color: #64748b; padding: 12px 0; }}
    .ok {{ color: #166534; font-size: 14px; margin-top: 8px; }}
    .error {{ color: #b91c1c; font-size: 14px; margin-top: 8px; }}
    .rating {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 12px; }}
    .rating button {{ margin: 0; border: 1px solid #cbd5e1; background: white; color: #111827; }}
    .rating button.active {{ background: #111827; color: white; border-color: #111827; }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <span class="pill">{escape(str(issue.get('status') or 'open'))}</span>
        <span class="pill">{escape(str(issue.get('priority') or 'normal'))}</span>
      </div>
      <h1>{escape(str(issue.get('subject') or 'Support request'))}</h1>
      <div class="subtle">{escape(str(issue.get('accountName') or issue.get('contactEmail') or ''))}</div>
    </header>
    <section class="panel">
      <div class="meta">Summary</div>
      <pre>{escape(str(issue.get('aiSummary') or 'Support is reviewing this request.'))}</pre>
    </section>
    <section class="stack" style="margin-top:16px">{message_html}</section>
    {help_section}
    <section class="panel" style="margin-top:16px">
      <div class="meta">Reply</div>
      <label for="senderEmail">Email</label>
      <input id="senderEmail" type="email" value="{escape(str(issue.get('contactEmail') or ''))}" />
      <label for="body">Message</label>
      <textarea id="body" rows="6"></textarea>
      <button id="send">Send message</button>
      <div id="status"></div>
    </section>
    <section class="panel" style="margin-top:16px">
      <div class="meta">Satisfaction</div>
      <p class="subtle">Rate this support experience.</p>
      <div class="rating" id="rating">
        <button type="button" data-rating="1" class="{('active' if feedback_rating == 1 else '')}">1</button>
        <button type="button" data-rating="2" class="{('active' if feedback_rating == 2 else '')}">2</button>
        <button type="button" data-rating="3" class="{('active' if feedback_rating == 3 else '')}">3</button>
        <button type="button" data-rating="4" class="{('active' if feedback_rating == 4 else '')}">4</button>
        <button type="button" data-rating="5" class="{('active' if feedback_rating == 5 else '')}">5</button>
      </div>
      <label for="feedbackComment">Comment</label>
      <textarea id="feedbackComment" rows="3">{escape(str(feedback.get('comment') or '') if isinstance(feedback, dict) else '')}</textarea>
      <button id="submitFeedback">Save rating</button>
      <div id="feedbackStatus"></div>
    </section>
  </main>
  <script>
    const portalToken = {token_json};
    const portalProjectId = {project_json};
    const button = document.getElementById('send');
    const statusEl = document.getElementById('status');
    let selectedRating = {feedback_rating};
    const feedbackButton = document.getElementById('submitFeedback');
    const feedbackStatusEl = document.getElementById('feedbackStatus');
    const helpSearchEl = document.getElementById('helpSearch');
    const helpSearchButton = document.getElementById('helpSearchButton');
    const helpResultsEl = document.getElementById('helpResults');
    const helpArticleEl = document.getElementById('helpArticle');
    function esc(value) {{
      return String(value || '').replace(/[&<>"']/g, (ch) => ({{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[ch]));
    }}
    function renderHelpArticles(articles) {{
      if (!helpResultsEl || !helpArticleEl) return;
      helpArticleEl.style.display = 'none';
      helpArticleEl.innerHTML = '';
      helpResultsEl.innerHTML = articles.length ? articles.map((article) => `
        <button type="button" class="article-button" data-article-id="${{esc(article.id)}}">
          <div class="article-title">${{esc(article.title || 'Untitled article')}}</div>
          <div class="article-excerpt">${{esc(article.excerpt || '')}}</div>
        </button>
      `).join('') : '<div class="empty">No public articles found.</div>';
    }}
    async function searchHelp(query) {{
      if (!portalProjectId || !helpSearchButton || !helpResultsEl) return;
      helpSearchButton.disabled = true;
      try {{
        const url = '/api/support/knowledge/' + encodeURIComponent(portalProjectId)
          + '?limit=5&q=' + encodeURIComponent(query || '');
        const res = await fetch(url);
        if (!res.ok) throw new Error('Could not load articles.');
        const data = await res.json();
        renderHelpArticles(Array.isArray(data.items) ? data.items : []);
      }} catch (err) {{
        helpResultsEl.innerHTML = '<div class="error">' + esc(err instanceof Error ? err.message : 'Could not load articles.') + '</div>';
      }} finally {{
        helpSearchButton.disabled = false;
      }}
    }}
    async function openHelpArticle(articleId) {{
      if (!portalProjectId || !helpArticleEl) return;
      const res = await fetch('/api/support/knowledge/' + encodeURIComponent(portalProjectId) + '/articles/' + encodeURIComponent(articleId));
      if (!res.ok) return;
      const article = await res.json();
      helpArticleEl.style.display = 'block';
      helpArticleEl.innerHTML = `
        <div class="article-title">${{esc(article.title || 'Untitled article')}}</div>
        <pre style="margin-top:8px">${{esc(article.body || article.excerpt || '')}}</pre>
      `;
    }}
    document.getElementById('rating').addEventListener('click', event => {{
      const target = event.target;
      if (!(target instanceof HTMLButtonElement)) return;
      selectedRating = Number(target.dataset.rating || '0');
      for (const item of document.querySelectorAll('#rating button')) item.classList.remove('active');
      target.classList.add('active');
    }});
    button.addEventListener('click', async () => {{
      const body = document.getElementById('body').value.trim();
      const senderEmail = document.getElementById('senderEmail').value.trim();
      if (!body) {{
        statusEl.className = 'error';
        statusEl.textContent = 'Message required.';
        return;
      }}
      button.disabled = true;
      statusEl.textContent = '';
      try {{
        const res = await fetch('/api/support/portal/' + encodeURIComponent(portalToken) + '/messages', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ body, senderEmail }})
        }});
        if (!res.ok) throw new Error('Could not send message.');
        statusEl.className = 'ok';
        statusEl.textContent = 'Message sent.';
        window.location.reload();
      }} catch (err) {{
        statusEl.className = 'error';
        statusEl.textContent = err instanceof Error ? err.message : 'Could not send message.';
      }} finally {{
        button.disabled = false;
      }}
    }});
    feedbackButton.addEventListener('click', async () => {{
      const comment = document.getElementById('feedbackComment').value.trim();
      const senderEmail = document.getElementById('senderEmail').value.trim();
      if (!selectedRating) {{
        feedbackStatusEl.className = 'error';
        feedbackStatusEl.textContent = 'Rating required.';
        return;
      }}
      feedbackButton.disabled = true;
      feedbackStatusEl.textContent = '';
      try {{
        const res = await fetch('/api/support/portal/' + encodeURIComponent(portalToken) + '/feedback', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ rating: selectedRating, comment, senderEmail }})
        }});
        if (!res.ok) throw new Error('Could not save rating.');
        feedbackStatusEl.className = 'ok';
        feedbackStatusEl.textContent = 'Rating saved.';
      }} catch (err) {{
        feedbackStatusEl.className = 'error';
        feedbackStatusEl.textContent = err instanceof Error ? err.message : 'Could not save rating.';
      }} finally {{
        feedbackButton.disabled = false;
      }}
    }});
    if (helpSearchButton && helpSearchEl && helpResultsEl) {{
      helpSearchButton.addEventListener('click', () => {{
        void searchHelp(helpSearchEl.value.trim());
      }});
      helpSearchEl.addEventListener('keydown', (event) => {{
        if (event.key === 'Enter') {{
          event.preventDefault();
          void searchHelp(helpSearchEl.value.trim());
        }}
      }});
      helpResultsEl.addEventListener('click', (event) => {{
        const target = event.target instanceof Element ? event.target.closest('[data-article-id]') : null;
        if (!target) return;
        void openHelpArticle(target.getAttribute('data-article-id') || '');
      }});
      void searchHelp('');
    }}
  </script>
</body>
</html>"""


@router.get("/support/portal/{token}", response_class=HTMLResponse)
async def portal_page(token: str) -> HTMLResponse:
    portal = _portal_or_404(token)
    return HTMLResponse(_render_portal_html(portal, token))
