import assert from 'node:assert/strict';
import http from 'node:http';
import https from 'node:https';

const host = process.env.TEST_HOST || 'fearghal.fnl.life';
const publicPort = Number(process.env.TEST_HTTPS_PORT || 443);
const adminPort = Number(process.env.TEST_ADMIN_PORT || 8443);
const httpPort = Number(process.env.TEST_HTTP_PORT || 80);
const cookies = new Map();

function request(path, { admin = false, plain = false, method = 'GET', body, headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const client = plain ? http : https;
    const req = client.request({
      hostname: admin ? (process.env.TEST_ADMIN_HOST || '127.0.0.1') : host,
      port: plain ? httpPort : admin ? adminPort : publicPort,
      servername: 'fearghal.fnl.life',
      rejectUnauthorized: process.env.TEST_SELF_SIGNED !== '1',
      path,
      method,
      timeout: 15000,
      headers: {
        Host: admin ? 'fearghal.fnl.life:8443' : 'fearghal.fnl.life',
        ...(admin ? { Cookie: [...cookies].map(([key, value]) => `${key}=${value}`).join('; ') } : {}),
        ...headers,
      },
    }, res => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { text += chunk; });
      res.on('end', () => {
        if (admin) {
          for (const cookie of res.headers['set-cookie'] || []) {
            const pair = cookie.split(';', 1)[0];
            const equals = pair.indexOf('=');
            cookies.set(pair.slice(0, equals), pair.slice(equals + 1));
          }
        }
        resolve({ status: res.statusCode, headers: res.headers, text });
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(new Error('Request timed out')); });
    req.end(body);
  });
}

const redirect = await request('/', { plain: true });
assert.equal(redirect.status, 301);
assert.equal(redirect.headers.location, 'https://fearghal.fnl.life/');

for (const path of [
  '/wp-admin', '/wp-admin/', '/wp-login.php', '/WP-LOGIN.php', '/xmlrpc.php',
  '/wp-json/', '/?rest_route=/wp/v2/users', '/?rest%5Froute=/wp/v2/users',
  '/wp%2dadmin/', '/wp-admin/../wp-login.php', '//wp-admin/', '/wp-login.php/extra',
  '/wp-config.php', '/.env', '/wp-admin/install.php',
]) {
  const result = await request(path);
  assert.equal(result.status, 403, `Public route must be blocked: ${path}`);
}
assert.equal((await request('/', { method: 'POST' })).status, 403);
assert.equal((await request('/?rest_route=/wp/v2/users', {
  headers: { 'X-Website-Admin': '1', 'X-Forwarded-For': '192.0.2.10' },
})).status, 403, 'Client headers must not bypass the private boundary');

const page = await request('/');
assert.equal(page.status, 200, 'An installed site must be available over public HTTPS');
assert.equal(page.headers['x-content-type-options'], 'nosniff');
assert.equal(page.headers['x-frame-options'], 'SAMEORIGIN');
assert.match(page.headers['strict-transport-security'], /max-age=31536000/);
assert.equal(page.headers['x-powered-by'], undefined);

const login = await request('/wp-login.php', { admin: true });
assert.equal(login.status, 200, 'Private HTTPS must serve the login page');
assert.ok(login.text.includes('https://fearghal.fnl.life:8443/wp-login.php'));
assert.notEqual(
  (await request('/wp-admin/install.php', { admin: true })).status,
  403,
  'Private HTTPS must allow the initial WordPress installer',
);

if (process.env.TEST_ADMIN_USER && process.env.TEST_ADMIN_PASSWORD) {
  const body = new URLSearchParams({
    log: process.env.TEST_ADMIN_USER,
    pwd: process.env.TEST_ADMIN_PASSWORD,
    'wp-submit': 'Log In',
    redirect_to: 'https://fearghal.fnl.life:8443/wp-admin/',
    testcookie: '1',
  }).toString();
  const signedIn = await request('/wp-login.php', {
    admin: true, method: 'POST', body,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  assert.equal(signedIn.status, 302, 'Private login must authenticate');
  assert.match(signedIn.headers.location, /^https:\/\/fearghal\.fnl\.life:8443\/wp-admin\//);
  assert.ok((signedIn.headers['set-cookie'] || []).some(cookie =>
    cookie.startsWith('wordpress_sec_') && /;\s*secure/i.test(cookie)), 'Admin cookie must be secure');

  const editor = await request('/wp-admin/post-new.php?post_type=page', { admin: true });
  assert.equal(editor.status, 200, 'Block editor must load privately');
  const settings = editor.text.match(/wpApiSettings\s*=\s*(\{[^\n;]+\})/);
  assert.ok(settings, 'Editor must include REST settings');
  const api = JSON.parse(settings[1]);
  assert.ok(api.root.startsWith('https://fearghal.fnl.life:8443/'), 'REST must stay on the private origin');
  const restURL = new URL(api.root);
  if (restURL.searchParams.has('rest_route')) {
    restURL.searchParams.set('rest_route', restURL.searchParams.get('rest_route') + 'wp/v2/users/me');
  } else {
    restURL.pathname += 'wp/v2/users/me';
  }
  const me = await request(restURL.pathname + restURL.search, { admin: true, headers: { 'X-WP-Nonce': api.nonce } });
  assert.equal(me.status, 200, 'Authenticated REST must work through the private listener');
}

const burst = await Promise.all(Array.from({ length: 65 }, (_, i) =>
  request('/', { headers: { 'X-Forwarded-For': `192.0.2.${i + 1}` } })));
assert.ok(burst.some(result => result.status === 429), 'Spoofed forwarding headers must not evade rate limiting');
assert.ok(burst.every(result => [200, 429].includes(result.status)), 'Rate-limited requests must return 429');

console.log('HTTPS, public route restrictions, private login, security headers, and rate limiting passed.');
