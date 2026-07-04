'use strict';

// Tiny demo HTTP service for codemagpieai.
// Endpoints:
//   GET  /              -> service info JSON
//   GET  /healthz       -> { status: "ok" }
//   GET  /hello/:name   -> { message: "Hello, <name>!" }
//   POST /echo          -> echoes back { received: <body>, at: <iso timestamp> }

const express = require('express');

function createApp() {
  const app = express();
  app.use(express.json());

  app.get('/', (_req, res) => {
    res.json({
      name: 'coding-agent-demo',
      description: 'Demo target repo for codemagpieai (create -> review).',
      endpoints: ['/', '/healthz', '/hello/:name', '/echo'],
    });
  });

  app.get('/healthz', (_req, res) => {
    res.json({ status: 'ok' });
  });

  app.get('/hello/:name', (req, res) => {
    const name = String(req.params.name || '').trim();
    if (!name) {
      return res.status(400).json({ error: 'name is required' });
    }
    res.json({ message: `Hello, ${name}!` });
  });

  app.post('/echo', (req, res) => {
    res.json({
      received: req.body ?? null,
      at: new Date().toISOString(),
    });
  });

  return app;
}

module.exports = { createApp };

if (require.main === module) {
  const port = Number(process.env.PORT || 3000);
  createApp().listen(port, () => {
    // eslint-disable-next-line no-console
    console.log(`coding-agent-demo listening on :${port}`);
  });
}