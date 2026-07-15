"""Public web chat support endpoints."""

import json
from html import escape
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from automail.db.pocketbase.client import create_web_chat_message, create_web_chat_session, get_web_chat_session
from automail.models import CamelCaseModel

router = APIRouter()


class WebChatSessionCreate(CamelCaseModel):
    channel_key: str = "web-chat"
    visitor_id: str = ""
    visitor_email: str = ""
    visitor_name: str = ""
    page_url: str = ""
    initial_message: str = ""
    metadata: dict[str, Any] | None = None


class WebChatMessageCreate(CamelCaseModel):
    body: str
    sender_name: str = ""
    sender_email: str = ""


def _script_json(value: str) -> str:
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


@router.post("/api/support/web-chat/{project_id}/sessions")
async def start_web_chat(project_id: str, body: WebChatSessionCreate) -> dict[str, Any]:
    try:
        return create_web_chat_session(
            tenant_id=None,
            project_id=project_id,
            channel_key=body.channel_key,
            visitor_id=body.visitor_id,
            visitor_email=body.visitor_email,
            visitor_name=body.visitor_name,
            page_url=body.page_url,
            initial_message=body.initial_message,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/support/web-chat/sessions/{session_key}")
async def get_web_chat(session_key: str) -> dict[str, Any]:
    session = get_web_chat_session(session_key)
    if not session:
        raise HTTPException(status_code=404, detail="Web chat session not found")
    return session


@router.post("/api/support/web-chat/sessions/{session_key}/messages")
async def add_web_chat_message(session_key: str, body: WebChatMessageCreate) -> dict[str, Any]:
    try:
        message = create_web_chat_message(
            session_key,
            body=body.body,
            sender_name=body.sender_name,
            sender_email=body.sender_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not message:
        raise HTTPException(status_code=404, detail="Web chat session not found")
    return message


def _render_web_chat_html(project_id: str, channel_key: str, page_url: str = "", page_title: str = "", referrer: str = "") -> str:
    project_json = _script_json(project_id)
    channel_json = _script_json(channel_key)
    page_url_json = _script_json(page_url)
    page_title_json = _script_json(page_title)
    referrer_json = _script_json(referrer)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Support chat</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f8fafc; color: #111827; }}
    main {{ max-width: 520px; margin: 0 auto; padding: 24px 16px; }}
    .panel, .message {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; }}
    .stack {{ display: grid; gap: 10px; }}
    .row {{ display: flex; gap: 8px; }}
    input, textarea {{ width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px; font: inherit; }}
    label {{ display: block; font-size: 13px; font-weight: 600; margin: 10px 0 6px; }}
    button {{ margin-top: 10px; border: 0; border-radius: 6px; background: #111827; color: white; padding: 10px 14px; font: inherit; cursor: pointer; }}
    .row button {{ margin-top: 0; }}
    .article-button {{ display: block; width: 100%; margin-top: 8px; border: 1px solid #e2e8f0; background: #fff; color: #111827; text-align: left; }}
    .article-title {{ font-weight: 600; }}
    .article-excerpt {{ color: #64748b; font-size: 13px; margin-top: 4px; }}
    button:disabled {{ opacity: .6; cursor: wait; }}
    pre {{ white-space: pre-wrap; font: inherit; margin: 0; line-height: 1.5; }}
    .meta {{ color: #64748b; font-size: 12px; margin-bottom: 6px; }}
    .error {{ color: #b91c1c; font-size: 14px; margin-top: 8px; }}
    .empty {{ color: #64748b; font-size: 14px; padding: 8px 0; }}
  </style>
</head>
<body>
  <main class="stack">
    <section class="panel" data-web-chat-help="true">
      <div class="meta">Help articles</div>
      <div class="row">
        <input id="helpSearch" placeholder="Search articles" />
        <button id="helpSearchButton" type="button">Search</button>
      </div>
      <div id="helpResults" class="stack" style="margin-top:10px"></div>
      <article id="helpArticle" class="message" style="display:none"></article>
    </section>
    <section class="panel">
      <label for="name">Name</label>
      <input id="name" autocomplete="name" />
      <label for="email">Email</label>
      <input id="email" type="email" autocomplete="email" />
      <label for="body">Message</label>
      <textarea id="body" rows="5"></textarea>
      <button id="send">Start chat</button>
      <div id="status"></div>
    </section>
    <section id="messages" class="stack"></section>
  </main>
  <script>
    const projectId = {project_json};
    const channelKey = {channel_json};
    const sourcePageUrl = {page_url_json} || window.location.href;
    const sourcePageTitle = {page_title_json} || document.title;
    const sourceReferrer = {referrer_json} || document.referrer;
    let sessionKey = window.localStorage.getItem('supportWebChatSession:' + projectId + ':' + channelKey) || '';
    const messagesEl = document.getElementById('messages');
    const statusEl = document.getElementById('status');
    const button = document.getElementById('send');
    const helpSearchEl = document.getElementById('helpSearch');
    const helpSearchButton = document.getElementById('helpSearchButton');
    const helpResultsEl = document.getElementById('helpResults');
    const helpArticleEl = document.getElementById('helpArticle');
    function esc(value) {{
      return String(value || '').replace(/[&<>"']/g, (ch) => ({{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[ch]));
    }}
    function render(messages) {{
      messagesEl.innerHTML = messages.map((message) => `
        <article class="message">
          <div class="meta">${{esc(message.sender || message.direction || 'Message')}}</div>
          <pre>${{esc(message.body || '')}}</pre>
        </article>
      `).join('');
    }}
    function metadata() {{
      return {{
        source: sourcePageUrl === window.location.href ? 'hosted_web_chat' : 'embed',
        pageTitle: sourcePageTitle,
        referrer: sourceReferrer
      }};
    }}
    function renderHelpArticles(articles) {{
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
      helpSearchButton.disabled = true;
      try {{
        const url = '/api/support/knowledge/' + encodeURIComponent(projectId)
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
      const res = await fetch('/api/support/knowledge/' + encodeURIComponent(projectId) + '/articles/' + encodeURIComponent(articleId));
      if (!res.ok) return;
      const article = await res.json();
      helpArticleEl.style.display = 'block';
      helpArticleEl.innerHTML = `
        <div class="article-title">${{esc(article.title || 'Untitled article')}}</div>
        <pre style="margin-top:8px">${{esc(article.body || article.excerpt || '')}}</pre>
      `;
    }}
    function syncButtonLabel() {{
      button.textContent = sessionKey ? 'Send message' : 'Start chat';
    }}
    function latestTicketId(data) {{
      return data.latestIssueId
        || data.issueId
        || (data.session && (data.session.latestIssueId || data.session.issueId))
        || (data.issue && data.issue.id)
        || '';
    }}
    function ticketCount(data) {{
      const ids = data.issueIds || (data.session && data.session.issueIds) || [];
      return Array.isArray(ids) && ids.length ? ids.length : latestTicketId(data) ? 1 : 0;
    }}
    function messageCount(data) {{
      if (typeof data.messageCount === 'number') return data.messageCount;
      if (data.session && typeof data.session.messageCount === 'number') return data.session.messageCount;
      const messages = data.messages || ((data.issue && data.issue.messages) || []);
      return Array.isArray(messages) ? messages.length : 0;
    }}
    function updateStatus(data) {{
      const ticketId = latestTicketId(data);
      if (!ticketId) return;
      const tickets = ticketCount(data);
      const messages = messageCount(data);
      const ticketLabel = tickets === 1 ? '1 ticket' : tickets + ' tickets';
      const messageLabel = messages === 1 ? '1 message' : messages + ' messages';
      statusEl.className = 'meta';
      statusEl.textContent = 'Ticket opened: ' + ticketId + ' - ' + ticketLabel + ' - ' + messageLabel;
      if (window.parent && window.parent !== window) {{
        window.parent.postMessage({{
          type: 'automail-support-chat-status',
          projectId,
          channelKey,
          latestTicketId: ticketId,
          ticketCount: tickets,
          messageCount: messages
        }}, '*');
      }}
    }}
    async function refresh() {{
      if (!sessionKey) return;
      const res = await fetch('/api/support/web-chat/sessions/' + encodeURIComponent(sessionKey));
      if (!res.ok) return;
      const data = await res.json();
      render(data.messages || ((data.issue && data.issue.messages) || []));
      updateStatus(data);
      syncButtonLabel();
    }}
    button.addEventListener('click', async () => {{
      const body = document.getElementById('body').value.trim();
      const visitorName = document.getElementById('name').value.trim();
      const visitorEmail = document.getElementById('email').value.trim();
      if (!body) {{
        statusEl.className = 'error';
        statusEl.textContent = 'Message required.';
        return;
      }}
      button.disabled = true;
      try {{
        if (!sessionKey) {{
          const res = await fetch('/api/support/web-chat/' + encodeURIComponent(projectId) + '/sessions', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ channelKey, visitorName, visitorEmail, pageUrl: sourcePageUrl, initialMessage: body, metadata: metadata() }})
          }});
          if (!res.ok) throw new Error('Could not start chat.');
          const data = await res.json();
          sessionKey = data.sessionKey;
          window.localStorage.setItem('supportWebChatSession:' + projectId + ':' + channelKey, sessionKey);
          syncButtonLabel();
        }} else {{
          const res = await fetch('/api/support/web-chat/sessions/' + encodeURIComponent(sessionKey) + '/messages', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ body, senderName: visitorName, senderEmail: visitorEmail }})
          }});
          if (!res.ok) throw new Error('Could not send message.');
        }}
        document.getElementById('body').value = '';
        await refresh();
      }} catch (err) {{
        statusEl.className = 'error';
        statusEl.textContent = err instanceof Error ? err.message : 'Could not send message.';
      }} finally {{
        button.disabled = false;
      }}
    }});
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
    syncButtonLabel();
    void searchHelp('');
    void refresh();
    window.setInterval(refresh, 10000);
  </script>
</body>
</html>"""


def _render_web_chat_embed_js(project_id: str, channel_key: str, label: str, position: str) -> str:
    project_json = json.dumps(project_id)
    channel_json = json.dumps(channel_key)
    label_json = json.dumps(label.strip()[:80] or "Support")
    position_json = json.dumps(position if position in {"bottom-left", "bottom-right"} else "bottom-right")
    return f"""(() => {{
  const projectId = {project_json};
  const channelKey = {channel_json};
  const label = {label_json};
  const position = {position_json};
  const instanceKey = projectId + ':' + channelKey;
  window.__automailSupportChat = window.__automailSupportChat || {{}};
  if (window.__automailSupportChat[instanceKey]) return;
  window.__automailSupportChat[instanceKey] = true;

  const currentScript = document.currentScript;
  const scriptUrl = currentScript && currentScript.src ? new URL(currentScript.src) : new URL(window.location.href);
  const baseUrl = scriptUrl.origin;
  const chatUrl = new URL('/support/web-chat/' + encodeURIComponent(projectId), baseUrl);
  chatUrl.searchParams.set('channel_key', channelKey);
  chatUrl.searchParams.set('page_url', window.location.href);
  if (document.title) chatUrl.searchParams.set('page_title', document.title);
  if (document.referrer) chatUrl.searchParams.set('referrer', document.referrer);

  const root = document.createElement('div');
  root.setAttribute('data-automail-support-chat', instanceKey);
  root.style.position = 'fixed';
  root.style.zIndex = '2147483647';
  root.style.bottom = '20px';
  root.style[position === 'bottom-left' ? 'left' : 'right'] = '20px';
  root.style.fontFamily = 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';

  const panel = document.createElement('div');
  panel.style.display = 'none';
  panel.style.width = 'min(380px, calc(100vw - 40px))';
  panel.style.height = 'min(620px, calc(100vh - 96px))';
  panel.style.marginBottom = '12px';
  panel.style.border = '1px solid #d1d5db';
  panel.style.borderRadius = '8px';
  panel.style.overflow = 'hidden';
  panel.style.background = '#ffffff';
  panel.style.boxShadow = '0 18px 50px rgba(15, 23, 42, 0.25)';

  const iframe = document.createElement('iframe');
  iframe.title = label;
  iframe.src = chatUrl.toString();
  iframe.loading = 'lazy';
  iframe.style.width = '100%';
  iframe.style.height = '100%';
  iframe.style.border = '0';
  panel.appendChild(iframe);

  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.setAttribute('aria-expanded', 'false');
  button.style.border = '0';
  button.style.borderRadius = '999px';
  button.style.background = '#111827';
  button.style.color = '#ffffff';
  button.style.padding = '12px 16px';
  button.style.font = '600 14px/1.2 Inter, ui-sans-serif, system-ui, sans-serif';
  button.style.cursor = 'pointer';
  button.style.boxShadow = '0 10px 30px rgba(15, 23, 42, 0.22)';

  button.addEventListener('click', () => {{
    const open = panel.style.display === 'none';
    panel.style.display = open ? 'block' : 'none';
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    button.textContent = open ? 'Close support' : label;
  }});

  window.addEventListener('message', (event) => {{
    if (event.origin !== baseUrl) return;
    const data = event.data || {{}};
    if (data.type !== 'automail-support-chat-status') return;
    if (data.projectId !== projectId || data.channelKey !== channelKey) return;
    if (data.latestTicketId) {{
      root.setAttribute('data-automail-support-chat-latest-ticket', String(data.latestTicketId));
      button.title = 'Ticket opened: ' + String(data.latestTicketId);
    }}
    if (Number.isFinite(Number(data.ticketCount))) {{
      root.setAttribute('data-automail-support-chat-ticket-count', String(Number(data.ticketCount)));
    }}
    if (Number.isFinite(Number(data.messageCount))) {{
      root.setAttribute('data-automail-support-chat-message-count', String(Number(data.messageCount)));
    }}
  }});

  root.appendChild(panel);
  root.appendChild(button);
  document.body.appendChild(root);
}})();
"""


@router.get("/support/web-chat/{project_id}", response_class=HTMLResponse)
async def web_chat_page(
    project_id: str,
    channel_key: str = "web-chat",
    page_url: str = "",
    page_title: str = "",
    referrer: str = "",
) -> HTMLResponse:
    return HTMLResponse(
        _render_web_chat_html(
            escape(project_id),
            escape(channel_key),
            page_url=page_url,
            page_title=page_title,
            referrer=referrer,
        )
    )


@router.get("/support/web-chat/{project_id}/embed.js")
async def web_chat_embed_script(
    project_id: str,
    channel_key: str = "web-chat",
    label: str = "Support",
    position: str = "bottom-right",
) -> Response:
    return Response(
        _render_web_chat_embed_js(project_id, channel_key, label, position),
        media_type="application/javascript; charset=utf-8",
    )
