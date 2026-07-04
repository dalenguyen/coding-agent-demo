'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { createApp } = require('./server');

function listen(app) {
  return new Promise((resolve) => {
    const srv = http.createServer(app);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      resolve({ srv, port });
    });
  });
}

function get(port, path) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      { host: '127.0.0.1', port, path, method: 'GET' },
      (res) => {
        let chunks = '';
        res.setEncoding('utf8');
        res.on('data', (c) => (chunks += c));
        res.on('end', () => resolve({ status: res.statusCode, body: chunks }));
      },
    );
    req.on('error', reject);
    req.end();
  });
}

function post(port, path, payload) {
  const data = JSON.stringify(payload);
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        host: '127.0.0.1',
        port,
        path,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(data),
        },
      },
      (res) => {
        let chunks = '';
        res.setEncoding('utf8');
        res.on('data', (c) => (chunks += c));
        res.on('end', () => resolve({ status: res.statusCode, body: chunks }));
      },
    );
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

test('GET / returns service info', async () => {
  const { srv, port } = await listen(createApp());
  try {
    const r = await get(port, '/');
    assert.equal(r.status, 200);
    const j = JSON.parse(r.body);
    assert.equal(j.name, 'coding-agent-demo');
    assert.ok(Array.isArray(j.endpoints));
  } finally {
    srv.close();
  }
});

test('GET /healthz returns ok', async () => {
  const { srv, port } = await listen(createApp());
  try {
    const r = await get(port, '/healthz');
    assert.equal(r.status, 200);
    assert.deepEqual(JSON.parse(r.body), { status: 'ok' });
  } finally {
    srv.close();
  }
});

test('GET /hello/:name greets the user', async () => {
  const { srv, port } = await listen(createApp());
  try {
    const r = await get(port, '/hello/World');
    assert.equal(r.status, 200);
    assert.deepEqual(JSON.parse(r.body), { message: 'Hello, World!' });
  } finally {
    srv.close();
  }
});

test('GET /hello/:name rejects empty name', async () => {
  const { srv, port } = await listen(createApp());
  try {
    // Express won't match /hello/  -> 404, but spaces are trimmed inside the
    // handler. We instead send a request that hits the handler with empty string
    // by URL-encoding a space.
    const r = await get(port, '/hello/%20');
    // /hello/%20  decodes to "/hello/ " (a space) which trims to "" -> 400
    assert.equal(r.status, 400);
  } finally {
    srv.close();
  }
});

test('POST /echo returns the body and a timestamp', async () => {
  const { srv, port } = await listen(createApp());
  try {
    const r = await post(port, '/echo', { hello: 'world' });
    assert.equal(r.status, 200);
    const j = JSON.parse(r.body);
    assert.deepEqual(j.received, { hello: 'world' });
    assert.match(j.at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
  } finally {
    srv.close();
  }
});