import { createServer } from 'node:http';

const host = process.env.E2E_DELIVERY_STUB_HOST || '127.0.0.1';
const port = Number(process.env.E2E_DELIVERY_STUB_PORT || '8190');
const deliveries = [];

function sendJson(response, status, payload) {
  response.writeHead(status, { 'Content-Type': 'application/json' });
  response.end(JSON.stringify(payload));
}

const server = createServer((request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    sendJson(response, 200, { status: 'ok' });
    return;
  }
  if (request.method === 'GET' && request.url === '/deliveries') {
    sendJson(response, 200, { items: deliveries });
    return;
  }
  if (request.method !== 'POST' || request.url !== '/deliver') {
    sendJson(response, 404, { error: 'not_found' });
    return;
  }

  const chunks = [];
  request.on('data', (chunk) => chunks.push(chunk));
  request.on('end', () => {
    try {
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      const messageId = String(body.messageId || body.message_id || `delivery-${deliveries.length + 1}`);
      deliveries.push({
        messageId,
        idempotencyKey: String(request.headers['idempotency-key'] || ''),
        body,
      });
      sendJson(response, 200, { id: `e2e:${messageId}`, status: 'accepted' });
    } catch {
      sendJson(response, 400, { error: 'invalid_json' });
    }
  });
});

server.listen(port, host);

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
