#!/usr/bin/env python3
import argparse
import os, subprocess, pathlib, shutil

def write_files(root: pathlib.Path, files: dict[str, str]):
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content.lstrip("\n"), encoding="utf-8")

def git_init(root: pathlib.Path):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "bench@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Bench"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial baseline"], cwd=root, check=True)

# =============================================================================
# CHALLENGE 1: c1-refactor-ts (10-file API refactor to Result<T, AppError> + AbortSignal)
# =============================================================================
C1_FILES = {
"package.json": """
{
  "name": "mini-rpc",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "test": "node --test test/rpc.test.ts"
  }
}
""",
"src/errors.ts": """
export class RpcError extends Error {
  status: number;
  constructor(message: string, status = 500) {
    super(message);
    this.name = 'RpcError';
    this.status = status;
  }
}

export class AuthError extends RpcError {
  constructor(message: string, status = 401) {
    super(message, status);
    this.name = 'AuthError';
  }
}

export class ValidationError extends RpcError {
  fields: Record<string, string>;
  constructor(message: string, fields: Record<string, string> = {}) {
    super(message, 400);
    this.name = 'ValidationError';
    this.fields = fields;
  }
}

export class RateLimitError extends RpcError {
  retryAfterMs: number;
  constructor(message: string, retryAfterMs = 1000) {
    super(message, 429);
    this.name = 'RateLimitError';
    this.retryAfterMs = retryAfterMs;
  }
}

export class NotFoundError extends RpcError {
  constructor(message: string) {
    super(message, 404);
    this.name = 'NotFoundError';
  }
}
""",
"src/types.ts": """
export interface RpcRequest {
  method: string;
  params: Record<string, unknown>;
  headers?: Record<string, string>;
}

export interface HandlerContext {
  method: string;
  headers: Record<string, string>;
  meta: Record<string, unknown>;
  user?: { id: string; scopes: string[] };
}

export type RpcHandler = (
  params: Record<string, unknown>,
  ctx: HandlerContext,
) => Promise<unknown>;

export type Middleware = (
  req: RpcRequest,
  ctx: HandlerContext,
  next: () => Promise<unknown>,
) => Promise<unknown>;
""",
"src/context.ts": """
import type { HandlerContext, RpcRequest } from './types.ts';

export function createContext(req: RpcRequest): HandlerContext {
  const normalizedHeaders: Record<string, string> = {};
  if (req.headers) {
    for (const [k, v] of Object.entries(req.headers)) {
      normalizedHeaders[k.toLowerCase()] = v;
    }
  }
  return {
    method: req.method,
    headers: normalizedHeaders,
    meta: {},
  };
}
""",
"src/router.ts": """
import { NotFoundError } from './errors.ts';
import { createContext } from './context.ts';
import type { Middleware, RpcHandler, RpcRequest } from './types.ts';

export class RpcRouter {
  private handlers = new Map<string, RpcHandler>();
  private middlewares: Middleware[] = [];

  use(mw: Middleware): this {
    this.middlewares.push(mw);
    return this;
  }

  register(method: string, handler: RpcHandler): this {
    this.handlers.set(method, handler);
    return this;
  }

  async dispatch(req: RpcRequest): Promise<unknown> {
    const ctx = createContext(req);
    const handler = this.handlers.get(req.method);

    let index = -1;
    const run = async (i: number): Promise<unknown> => {
      if (i <= index) {
        throw new Error('next() called multiple times');
      }
      index = i;
      if (i < this.middlewares.length) {
        return this.middlewares[i](req, ctx, () => run(i + 1));
      }
      if (!handler) {
        throw new NotFoundError(`Unknown method: ${req.method}`);
      }
      return handler(req.params, ctx);
    };

    return run(0);
  }
}
""",
"src/middleware/auth.ts": """
import { AuthError } from '../errors.ts';
import type { Middleware } from '../types.ts';

export interface TokenRecord {
  id: string;
  scopes: string[];
}

export interface AuthOptions {
  tokens: Record<string, TokenRecord>;
  requiredScopes?: Record<string, string[]>;
  publicMethods?: string[];
}

export function createAuthMiddleware(opts: AuthOptions): Middleware {
  const publicSet = new Set(opts.publicMethods ?? []);

  return async (req, ctx, next) => {
    if (publicSet.has(req.method)) {
      return next();
    }

    const authHeader = ctx.headers['authorization'];
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      throw new AuthError('Missing bearer token', 401);
    }

    const token = authHeader.slice('Bearer '.length).trim();
    const record = opts.tokens[token];
    if (!record) {
      throw new AuthError('Invalid token', 401);
    }

    ctx.user = { id: record.id, scopes: [...record.scopes] };

    const needed = opts.requiredScopes?.[req.method] ?? [];
    for (const scope of needed) {
      if (!record.scopes.includes(scope)) {
        throw new AuthError(`Missing required scope: ${scope}`, 403);
      }
    }

    return next();
  };
}
""",
"src/middleware/rateLimit.ts": """
import { RateLimitError } from '../errors.ts';
import type { Middleware } from '../types.ts';

export interface RateLimitOptions {
  maxRequests: number;
  windowMs: number;
  now?: () => number;
  keyFn?: (headers: Record<string, string>, method: string) => string;
}

export function createRateLimitMiddleware(opts: RateLimitOptions): Middleware {
  const now = opts.now ?? (() => Date.now());
  const keyFn = opts.keyFn ?? ((h) => h['x-client-id'] ?? 'anonymous');
  const buckets = new Map<string, number[]>();

  return async (req, ctx, next) => {
    const key = keyFn(ctx.headers, req.method);
    const currentTime = now();
    const cutoff = currentTime - opts.windowMs;

    const timestamps = (buckets.get(key) ?? []).filter((t) => t > cutoff);
    if (timestamps.length >= opts.maxRequests) {
      const oldest = timestamps[0];
      const retryAfterMs = Math.max(1, oldest + opts.windowMs - currentTime);
      buckets.set(key, timestamps);
      throw new RateLimitError(`Rate limit exceeded for ${key}`, retryAfterMs);
    }

    timestamps.push(currentTime);
    buckets.set(key, timestamps);
    return next();
  };
}
""",
"src/middleware/validate.ts": """
import { ValidationError } from '../errors.ts';
import type { Middleware } from '../types.ts';

export type FieldRule = 'string' | 'number' | 'boolean';
export type SchemaMap = Record<string, Record<string, FieldRule>>;

export function createValidationMiddleware(schemas: SchemaMap): Middleware {
  return async (req, _ctx, next) => {
    const schema = schemas[req.method];
    if (!schema) {
      return next();
    }

    const fields: Record<string, string> = {};
    for (const [field, expectedType] of Object.entries(schema)) {
      const val = req.params[field];
      if (val === undefined || val === null) {
        fields[field] = 'required';
      } else if (typeof val !== expectedType) {
        fields[field] = `expected ${expectedType}`;
      }
    }

    if (Object.keys(fields).length > 0) {
      throw new ValidationError(`Invalid params for ${req.method}`, fields);
    }

    return next();
  };
}
""",
"src/middleware/logging.ts": """
import type { Middleware } from '../types.ts';

export interface LogEntry {
  method: string;
  ok: boolean;
  code?: string;
  durationMs: number;
}

export function createLoggingMiddleware(
  sink: (entry: LogEntry) => void,
  now: () => number = () => Date.now(),
): Middleware {
  return async (req, _ctx, next) => {
    const start = now();
    try {
      const result = await next();
      sink({ method: req.method, ok: true, durationMs: now() - start });
      return result;
    } catch (err) {
      sink({
        method: req.method,
        ok: false,
        code: err instanceof Error ? err.name : 'UNKNOWN',
        durationMs: now() - start,
      });
      throw err;
    }
  };
}
""",
"src/adapters/http.ts": """
import { RpcError } from '../errors.ts';
import type { RpcRouter } from '../router.ts';

export interface HttpRequest {
  method: string;
  params: Record<string, unknown>;
  headers?: Record<string, string>;
}

export interface HttpResponse {
  status: number;
  body: Record<string, unknown>;
}

export interface LegacyResponse {
  status: number;
  data?: unknown;
  error?: string;
}

export function createHttpAdapter(router: RpcRouter) {
  return async (req: HttpRequest): Promise<HttpResponse> => {
    try {
      const data = await router.dispatch({
        method: req.method,
        params: req.params,
        headers: req.headers,
      });
      return { status: 200, body: { ok: true, data } };
    } catch (err) {
      if (err instanceof RpcError) {
        return { status: err.status, body: { ok: false, error: err.message } };
      }
      return {
        status: 500,
        body: { ok: false, error: err instanceof Error ? err.message : 'Internal error' },
      };
    }
  };
}

export function createLegacyHandler(router: RpcRouter) {
  return async (
    method: string,
    params: Record<string, unknown>,
    headers?: Record<string, string>,
  ): Promise<LegacyResponse> => {
    try {
      const data = await router.dispatch({ method, params, headers });
      return { status: 200, data };
    } catch (err) {
      if (err instanceof RpcError) {
        return { status: err.status, error: err.message };
      }
      return {
        status: 500,
        error: err instanceof Error ? err.message : 'Internal error',
      };
    }
  };
}
""",
"src/client.ts": """
import { RateLimitError } from './errors.ts';
import type { RpcRouter } from './router.ts';

export interface CallOptions {
  headers?: Record<string, string>;
  maxRetries?: number;
  retryDelayMs?: number;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class RpcClient {
  private router: RpcRouter;
  constructor(router: RpcRouter) {
    this.router = router;
  }

  async call(
    method: string,
    params: Record<string, unknown>,
    opts: CallOptions = {},
  ): Promise<unknown> {
    const maxRetries = opts.maxRetries ?? 0;
    const retryDelayMs = opts.retryDelayMs ?? 10;

    let attempt = 0;
    while (true) {
      try {
        return await this.router.dispatch({
          method,
          params,
          headers: opts.headers,
        });
      } catch (err) {
        if (err instanceof RateLimitError && attempt < maxRetries) {
          attempt++;
          await delay(retryDelayMs);
          continue;
        }
        throw err;
      }
    }
  }
}
""",
"src/index.ts": """
export * from './errors.ts';
export * from './types.ts';
export * from './context.ts';
export * from './router.ts';
export * from './middleware/auth.ts';
export * from './middleware/rateLimit.ts';
export * from './middleware/validate.ts';
export * from './middleware/logging.ts';
export * from './adapters/http.ts';
export * from './client.ts';
""",
"test/rpc.test.ts": """
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  RpcRouter,
  createAuthMiddleware,
  createRateLimitMiddleware,
  createValidationMiddleware,
  createLoggingMiddleware,
  createHttpAdapter,
  createLegacyHandler,
  RpcClient,
  type LogEntry,
} from '../src/index.ts';

function buildRouter(logs: LogEntry[], clock = () => 1000) {
  const router = new RpcRouter();
  router
    .use(createLoggingMiddleware((e) => logs.push(e), clock))
    .use(
      createAuthMiddleware({
        tokens: {
          'tok-admin': { id: 'u1', scopes: ['read', 'write'] },
          'tok-read': { id: 'u2', scopes: ['read'] },
        },
        requiredScopes: { 'items.create': ['write'] },
        publicMethods: ['health'],
      }),
    )
    .use(
      createRateLimitMiddleware({
        maxRequests: 2,
        windowMs: 1000,
        now: clock,
      }),
    )
    .use(
      createValidationMiddleware({
        'items.create': { name: 'string', qty: 'number' },
      }),
    );

  router.register('health', async () => ({ status: 'ok' }));
  router.register('items.create', async (params, ctx) => ({
    createdBy: ctx.user?.id,
    name: params.name,
    qty: params.qty,
  }));
  return router;
}

describe('mini-rpc baseline', () => {
  it('handles public health method', async () => {
    const logs: LogEntry[] = [];
    const router = buildRouter(logs);
    const res = await router.dispatch({ method: 'health', params: {} });
    assert.deepEqual(res, { status: 'ok' });
    assert.equal(logs.length, 1);
    assert.equal(logs[0].ok, true);
  });

  it('rejects unauthorized requests', async () => {
    const logs: LogEntry[] = [];
    const router = buildRouter(logs);
    await assert.rejects(
      () => router.dispatch({ method: 'items.create', params: { name: 'a', qty: 1 } }),
      /Missing bearer token/,
    );
  });

  it('adapts HTTP and legacy handlers', async () => {
    const logs: LogEntry[] = [];
    const router = buildRouter(logs);
    const http = createHttpAdapter(router);
    const legacy = createLegacyHandler(router);

    const r1 = await http({
      method: 'items.create',
      params: { name: 'widget', qty: 3 },
      headers: { Authorization: 'Bearer tok-admin' },
    });
    assert.equal(r1.status, 200);

    const r2 = await legacy('items.create', { name: 'widget', qty: 3 }, {
      Authorization: 'Bearer tok-read',
    });
    assert.equal(r2.status, 403);
  });

  it('client calls method', async () => {
    const logs: LogEntry[] = [];
    const router = buildRouter(logs);
    const client = new RpcClient(router);
    const res = await client.call('health', {});
    assert.deepEqual(res, { status: 'ok' });
  });
});
"""
}

C1_GRADING = {
"hidden_grading.test.ts": """
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  RpcRouter,
  createAppError,
  toAppError,
  ok,
  err,
  createContext,
  createAuthMiddleware,
  createRateLimitMiddleware,
  createValidationMiddleware,
  createLoggingMiddleware,
  createHttpAdapter,
  createLegacyHandler,
  RpcClient,
  type LogEntry,
  type AppError,
  type Result,
} from '../src/index.ts';

function buildFullRouter(logs: LogEntry[], clockRef = { now: 1000 }) {
  const router = new RpcRouter();
  router
    .use(createLoggingMiddleware((e) => logs.push(e), () => clockRef.now))
    .use(
      createAuthMiddleware({
        tokens: {
          'tok-admin': { id: 'u1', scopes: ['read', 'write'] },
          'tok-read': { id: 'u2', scopes: ['read'] },
        },
        requiredScopes: { 'items.create': ['write'] },
        publicMethods: ['health', 'slow', 'boom', 'flaky', 'abortAware'],
      }),
    )
    .use(
      createRateLimitMiddleware({
        maxRequests: 2,
        windowMs: 1000,
        now: () => clockRef.now,
      }),
    )
    .use(
      createValidationMiddleware({
        'items.create': { name: 'string', qty: 'number' },
      }),
    );

  router.register('health', async () => ok({ status: 'ok' }));
  router.register('items.create', async (params, ctx) =>
    ok({ createdBy: ctx.user?.id, name: params.name, qty: params.qty }),
  );
  router.register('boom', async () => {
    throw new Error('unexpected explosion');
  });
  router.register('slow', async (params, ctx) => {
    const ms = Number(params.ms ?? 200);
    return new Promise((resolve) => {
      const t = setTimeout(() => resolve(ok({ done: true })), ms);
      ctx.signal.addEventListener('abort', () => {
        clearTimeout(t);
        resolve(err(createAppError('CANCELLED', 'handler saw abort', { retryable: false })));
      }, { once: true });
    });
  });
  router.register('slowIgnoreSignal', async (params) => {
    const ms = Number(params.ms ?? 300);
    await new Promise((r) => setTimeout(r, ms));
    return ok({ done: true });
  });

  return router;
}

describe('C1 hidden grading suite', () => {
  it('1. createAppError and toAppError preserve AppError and map AbortError / unknown', () => {
    const existing = createAppError('RATE_LIMITED', 'slow down', { retryable: true, details: { retryAfterMs: 500 } });
    assert.equal(existing.code, 'RATE_LIMITED');
    assert.equal(existing.retryable, true);
    assert.deepEqual(existing.details, { retryAfterMs: 500 });
    assert.strictEqual(toAppError(existing), existing);

    const abortErr = new DOMException('aborted', 'AbortError');
    const mappedAbort = toAppError(abortErr);
    assert.equal(mappedAbort.code, 'CANCELLED');
    assert.equal(mappedAbort.retryable, false);

    const unknown = toAppError(new TypeError('bad type'));
    assert.equal(unknown.code, 'INTERNAL');
    assert.equal(unknown.retryable, false);
    assert.match(unknown.message, /bad type/);
  });

  it('2. ok() and err() constructors produce valid Result objects', () => {
    const r1 = ok(123);
    assert.equal(r1.ok, true);
    assert.equal(r1.value, 123);
    const e = createAppError('NOT_FOUND', 'missing', { retryable: false });
    const r2 = err(e);
    assert.equal(r2.ok, false);
    assert.equal(r2.error.code, 'NOT_FOUND');
  });

  it('3. auth middleware returns UNAUTHORIZED (401) and FORBIDDEN (403) as Result without throwing', async () => {
    const logs: LogEntry[] = [];
    const router = buildFullRouter(logs);

    const r1 = await router.dispatch({ method: 'items.create', params: { name: 'a', qty: 1 } });
    assert.equal(r1.ok, false);
    if (!r1.ok) {
      assert.equal(r1.error.code, 'UNAUTHORIZED');
      assert.equal(r1.error.retryable, false);
    }

    const r2 = await router.dispatch({
      method: 'items.create',
      params: { name: 'a', qty: 1 },
      headers: { Authorization: 'Bearer bad' },
    });
    assert.equal(r2.ok, false);
    if (!r2.ok) assert.equal(r2.error.code, 'UNAUTHORIZED');

    const r3 = await router.dispatch({
      method: 'items.create',
      params: { name: 'a', qty: 1 },
      headers: { Authorization: 'Bearer tok-read' },
    });
    assert.equal(r3.ok, false);
    if (!r3.ok) {
      assert.equal(r3.error.code, 'FORBIDDEN');
      assert.equal(r3.error.retryable, false);
    }
  });

  it('4. validation middleware returns VALIDATION_ERROR with details.fields', async () => {
    const logs: LogEntry[] = [];
    const router = buildFullRouter(logs);
    const r = await router.dispatch({
      method: 'items.create',
      params: { name: 42 },
      headers: { Authorization: 'Bearer tok-admin' },
    });
    assert.equal(r.ok, false);
    if (!r.ok) {
      assert.equal(r.error.code, 'VALIDATION_ERROR');
      assert.equal(r.error.retryable, false);
      const fields = r.error.details?.fields as Record<string, string>;
      assert.ok(fields);
      assert.ok(fields.name);
      assert.ok(fields.qty);
    }
  });

  it('5. rateLimit middleware returns retryable RATE_LIMITED with details.retryAfterMs', async () => {
    const logs: LogEntry[] = [];
    const clock = { now: 5000 };
    const router = buildFullRouter(logs, clock);

    await router.dispatch({ method: 'health', params: {}, headers: { 'x-client-id': 'c1' } });
    clock.now = 5100;
    await router.dispatch({ method: 'health', params: {}, headers: { 'x-client-id': 'c1' } });
    clock.now = 5200;
    const r3 = await router.dispatch({ method: 'health', params: {}, headers: { 'x-client-id': 'c1' } });

    assert.equal(r3.ok, false);
    if (!r3.ok) {
      assert.equal(r3.error.code, 'RATE_LIMITED');
      assert.equal(r3.error.retryable, true);
      assert.equal(r3.error.details?.retryAfterMs, 800);
    }
  });

  it('6. unknown method returns NOT_FOUND as Result', async () => {
    const logs: LogEntry[] = [];
    const router = buildFullRouter(logs);
    const r = await router.dispatch({
      method: 'no.such.method',
      params: {},
      headers: { Authorization: 'Bearer tok-admin' },
    });
    assert.equal(r.ok, false);
    if (!r.ok) {
      assert.equal(r.error.code, 'NOT_FOUND');
      assert.equal(r.error.retryable, false);
    }
  });

  it('7. router catches unexpected thrown errors from handlers and middlewares into INTERNAL Result', async () => {
    const logs: LogEntry[] = [];
    const router = buildFullRouter(logs);
    const r = await router.dispatch({ method: 'boom', params: {} });
    assert.equal(r.ok, false);
    if (!r.ok) {
      assert.equal(r.error.code, 'INTERNAL');
      assert.equal(r.error.retryable, false);
      assert.match(r.error.message, /unexpected explosion/);
    }
    // Middleware that throws directly
    const r2 = new RpcRouter();
    r2.use(async () => {
      throw new Error('mw crash');
    });
    r2.register('ping', async () => ok('pong'));
    const res2 = await r2.dispatch({ method: 'ping', params: {} });
    assert.equal(res2.ok, false);
    if (!res2.ok) {
      assert.equal(res2.error.code, 'INTERNAL');
    }
  });

  it('8. logging middleware logs ok:false with structured error code for both returned Result errors and thrown exceptions', async () => {
    const logs: LogEntry[] = [];
    const clock = { now: 1000 };
    const router = buildFullRouter(logs, clock);

    await router.dispatch({ method: 'items.create', params: {} }); // UNAUTHORIZED (returned err)
    await router.dispatch({ method: 'boom', params: {} }); // INTERNAL (thrown)
    await router.dispatch({ method: 'health', params: {} }); // ok

    assert.equal(logs.length, 3);
    assert.equal(logs[0].ok, false);
    assert.equal(logs[0].code, 'UNAUTHORIZED');
    assert.equal(logs[1].ok, false);
    assert.equal(logs[1].code, 'INTERNAL');
    assert.equal(logs[2].ok, true);
    assert.equal(logs[2].code, undefined);
  });

  it('9. pre-aborted AbortSignal short-circuits dispatch without executing middlewares or handler', async () => {
    let mwCalled = false;
    let handlerCalled = false;
    const router = new RpcRouter();
    router.use(async (_req, _ctx, next) => {
      mwCalled = true;
      return next();
    });
    router.register('test', async () => {
      handlerCalled = true;
      return ok('hi');
    });

    const ac = new AbortController();
    ac.abort();
    const r = await router.dispatch({ method: 'test', params: {} }, { signal: ac.signal });
    assert.equal(r.ok, false);
    if (!r.ok) {
      assert.equal(r.error.code, 'CANCELLED');
      assert.equal(r.error.retryable, false);
    }
    assert.equal(mwCalled, false);
    assert.equal(handlerCalled, false);
  });

  it('10. timeoutMs races pending handler and returns retryable TIMEOUT immediately', async () => {
    const router = new RpcRouter();
    let signalAborted = false;
    router.register('hang', async (_p, ctx) => {
      ctx.signal.addEventListener('abort', () => { signalAborted = true; });
      await new Promise((r) => setTimeout(r, 500));
      return ok('late');
    });

    const start = Date.now();
    const r = await router.dispatch({ method: 'hang', params: {} }, { timeoutMs: 40 });
    const elapsed = Date.now() - start;

    assert.equal(r.ok, false);
    if (!r.ok) {
      assert.equal(r.error.code, 'TIMEOUT');
      assert.equal(r.error.retryable, true);
    }
    assert.ok(elapsed < 250, `Expected fast timeout settle, got ${elapsed}ms`);
    assert.equal(signalAborted, true);
  });

  it('11. external abort during in-flight handler returns CANCELLED (not TIMEOUT) even when timeoutMs is also set', async () => {
    const router = new RpcRouter();
    router.register('hang', async () => {
      await new Promise((r) => setTimeout(r, 500));
      return ok('late');
    });

    const ac = new AbortController();
    setTimeout(() => ac.abort(), 30);
    const start = Date.now();
    const r = await router.dispatch(
      { method: 'hang', params: {} },
      { signal: ac.signal, timeoutMs: 400 },
    );
    const elapsed = Date.now() - start;

    assert.equal(r.ok, false);
    if (!r.ok) {
      assert.equal(r.error.code, 'CANCELLED');
      assert.equal(r.error.retryable, false);
    }
    assert.ok(elapsed < 250, `Expected fast cancel settle, got ${elapsed}ms`);
  });

  it('12. timeout firing before external abort returns TIMEOUT when both are provided', async () => {
    const router = new RpcRouter();
    router.register('hang', async () => {
      await new Promise((r) => setTimeout(r, 500));
      return ok('late');
    });

    const ac = new AbortController();
    const r = await router.dispatch(
      { method: 'hang', params: {} },
      { signal: ac.signal, timeoutMs: 30 },
    );
    assert.equal(r.ok, false);
    if (!r.ok) {
      assert.equal(r.error.code, 'TIMEOUT');
      assert.equal(r.error.retryable, true);
    }
  });

  it('13. createHttpAdapter maps every ErrorCode to the exact specified HTTP status and structured body', async () => {
    const cases: Array<[AppError['code'], number, boolean]> = [
      ['VALIDATION_ERROR', 400, false],
      ['UNAUTHORIZED', 401, false],
      ['FORBIDDEN', 403, false],
      ['NOT_FOUND', 404, false],
      ['TIMEOUT', 408, true],
      ['RATE_LIMITED', 429, true],
      ['CANCELLED', 499, false],
      ['INTERNAL', 500, false],
    ];
    const router = new RpcRouter();
    for (const [code, _status, retryable] of cases) {
      router.register(`m_${code}`, async () =>
        err(createAppError(code, `msg_${code}`, { retryable, details: { tag: code } })),
      );
    }
    router.register('m_ok', async () => ok({ hello: 'world' }));

    const http = createHttpAdapter(router);
    const okRes = await http({ method: 'm_ok', params: {} });
    assert.equal(okRes.status, 200);
    assert.deepEqual(okRes.body, { ok: true, data: { hello: 'world' } });

    for (const [code, status, retryable] of cases) {
      const res = await http({ method: `m_${code}`, params: {} });
      assert.equal(res.status, status, `Wrong HTTP status for ${code}`);
      assert.equal(res.body.ok, false);
      const e = res.body.error as Record<string, unknown>;
      assert.equal(e.code, code);
      assert.equal(e.message, `msg_${code}`);
      assert.equal(e.retryable, retryable);
      assert.deepEqual(e.details, { tag: code });
    }
  });

  it('14. createHttpAdapter passes signal and timeoutMs through to router', async () => {
    const router = new RpcRouter();
    router.register('slow', async () => {
      await new Promise((r) => setTimeout(r, 300));
      return ok(1);
    });
    const http = createHttpAdapter(router);
    const res = await http({ method: 'slow', params: {}, timeoutMs: 30 } as any);
    assert.equal(res.status, 408);

    const ac = new AbortController();
    ac.abort();
    const res2 = await http({ method: 'slow', params: {}, signal: ac.signal } as any);
    assert.equal(res2.status, 499);
  });

  it('15. createLegacyHandler preserves legacy shape without throwing for all error codes', async () => {
    const router = new RpcRouter();
    router.register('ok', async () => ok({ x: 1 }));
    router.register('rl', async () => err(createAppError('RATE_LIMITED', 'too fast', { retryable: true })));
    router.register('to', async () => err(createAppError('TIMEOUT', 'timed out', { retryable: true })));
    router.register('crash', async () => { throw new Error('kaboom'); });

    const legacy = createLegacyHandler(router);
    assert.deepEqual(await legacy('ok', {}), { status: 200, data: { x: 1 } });
    assert.deepEqual(await legacy('rl', {}), { status: 429, error: 'too fast' });
    assert.deepEqual(await legacy('to', {}), { status: 408, error: 'timed out' });
    const nf = await legacy('missing', {});
    assert.equal(nf.status, 404);
    assert.equal(typeof nf.error, 'string');
    const cr = await legacy('crash', {});
    assert.equal(cr.status, 500);
    assert.match(cr.error ?? '', /kaboom/);
  });

  it('16. RpcClient retries retryable errors (RATE_LIMITED, TIMEOUT) up to maxRetries and returns Result', async () => {
    let calls = 0;
    const router = new RpcRouter();
    router.register('flaky', async () => {
      calls++;
      if (calls < 3) {
        return err(createAppError('RATE_LIMITED', 'retry me', { retryable: true }));
      }
      return ok({ attempts: calls });
    });

    const client = new RpcClient(router);
    const res = await client.call('flaky', {}, { maxRetries: 3, retryDelayMs: 10 });
    assert.equal(res.ok, true);
    if (res.ok) assert.deepEqual(res.value, { attempts: 3 });
    assert.equal(calls, 3);
  });

  it('17. RpcClient NEVER retries non-retryable errors', async () => {
    let calls = 0;
    const router = new RpcRouter();
    router.register('bad', async () => {
      calls++;
      return err(createAppError('VALIDATION_ERROR', 'bad input', { retryable: false }));
    });
    const client = new RpcClient(router);
    const res = await client.call('bad', {}, { maxRetries: 5, retryDelayMs: 5 });
    assert.equal(res.ok, false);
    if (!res.ok) assert.equal(res.error.code, 'VALIDATION_ERROR');
    assert.equal(calls, 1);
  });

  it('18. RpcClient aborts immediately during retry backoff delay without waiting full retryDelayMs', async () => {
    let calls = 0;
    const router = new RpcRouter();
    router.register('alwaysRL', async () => {
      calls++;
      return err(createAppError('RATE_LIMITED', 'busy', { retryable: true }));
    });
    const client = new RpcClient(router);
    const ac = new AbortController();
    setTimeout(() => ac.abort(), 30);

    const start = Date.now();
    const res = await client.call('alwaysRL', {}, {
      maxRetries: 3,
      retryDelayMs: 2000,
      signal: ac.signal,
    });
    const elapsed = Date.now() - start;

    assert.equal(res.ok, false);
    if (!res.ok) assert.equal(res.error.code, 'CANCELLED');
    assert.equal(calls, 1);
    assert.ok(elapsed < 300, `Client waited during backoff instead of aborting: ${elapsed}ms`);
  });

  it('19. RpcClient passes timeoutMs per attempt so retry can succeed after a timeout', async () => {
    let calls = 0;
    const router = new RpcRouter();
    router.register('slowFirst', async () => {
      calls++;
      if (calls === 1) {
        await new Promise((r) => setTimeout(r, 200));
        return ok('too slow');
      }
      return ok('fast');
    });
    const client = new RpcClient(router);
    const res = await client.call('slowFirst', {}, { timeoutMs: 40, maxRetries: 2, retryDelayMs: 5 });
    assert.equal(res.ok, true);
    if (res.ok) assert.equal(res.value, 'fast');
    assert.equal(calls, 2);
  });
});
"""
}

# =============================================================================
# CHALLENGE 2: c2-feature-ts (7-file Job/Webhook Dispatcher feature implementation)
# =============================================================================
C2_FILES = {
"package.json": """
{
  "name": "job-dispatch",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "test": "node --test test/dispatcher.test.ts"
  }
}
""",
"src/types.ts": """
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'dead' | 'cancelled';

export interface JobInput<T = unknown> {
  tenantId: string;
  payload: T;
  maxAttempts?: number;
  idempotencyKey?: string;
  idempotencyTtlMs?: number;
}

export interface JobRecord<T = unknown> {
  id: string;
  tenantId: string;
  payload: T;
  status: JobStatus;
  attempts: number;
  maxAttempts: number;
  idempotencyKey?: string;
  idempotencyTtlMs?: number;
  createdAt: number;
  completedAt?: number;
  failedAt?: number;
  lastError?: string;
}

export interface EnqueueResult {
  jobId: string;
  deduplicated: boolean;
}

export interface DrainOptions {
  timeoutMs?: number;
}

export interface DrainResult {
  drained: boolean;
  cancelled: string[];
}

export type JobHandler<T = unknown> = (
  job: JobRecord<T>,
  signal: AbortSignal,
) => Promise<void>;

export interface DispatcherConfig {
  maxConcurrency: number;
  maxConcurrencyPerTenant?: number;
  defaultMaxAttempts?: number;
  baseRetryDelayMs?: number;
  defaultIdempotencyTtlMs?: number;
  clock?: () => number;
}
""",
"src/backoff.ts": """
export function computeBackoffMs(attempt: number, baseDelayMs: number): number {
  if (baseDelayMs <= 0) return 0;
  return baseDelayMs * Math.pow(2, Math.max(0, attempt - 1));
}
""",
"src/store.ts": """
import type { JobRecord } from './types.ts';

export class JobStore {
  private jobs = new Map<string, JobRecord>();
  private seq = 0;

  nextId(): string {
    this.seq += 1;
    return `job_${this.seq}`;
  }

  save(job: JobRecord): void {
    this.jobs.set(job.id, job);
  }

  get(jobId: string): JobRecord | undefined {
    return this.jobs.get(jobId);
  }

  all(): JobRecord[] {
    return Array.from(this.jobs.values());
  }
}
""",
"src/worker.ts": """
import type { JobHandler, JobRecord } from './types.ts';

export interface RunAttemptResult {
  ok: boolean;
  error?: unknown;
  nonRetryable?: boolean;
}

export async function runJobAttempt(
  job: JobRecord,
  handler: JobHandler,
  signal: AbortSignal,
): Promise<RunAttemptResult> {
  try {
    await handler(job, signal);
    return { ok: true };
  } catch (err) {
    const nonRetryable = Boolean(
      err && typeof err === 'object' && 'nonRetryable' in err && (err as { nonRetryable?: unknown }).nonRetryable === true,
    );
    return { ok: false, error: err, nonRetryable };
  }
}
""",
"src/dispatcher.ts": """
import { computeBackoffMs } from './backoff.ts';
import { JobStore } from './store.ts';
import { runJobAttempt } from './worker.ts';
import type {
  DispatcherConfig,
  DrainOptions,
  DrainResult,
  EnqueueResult,
  JobHandler,
  JobInput,
  JobRecord,
} from './types.ts';

export class JobDispatcher {
  private readonly config: Required<Omit<DispatcherConfig, 'clock'>> & { clock: () => number };
  private readonly store = new JobStore();
  private readonly handler: JobHandler;
  private readonly queue: string[] = [];
  private activeCount = 0;
  private running = false;

  constructor(handler: JobHandler, config: DispatcherConfig) {
    this.handler = handler;
    this.config = {
      maxConcurrency: config.maxConcurrency,
      maxConcurrencyPerTenant: config.maxConcurrencyPerTenant ?? Infinity,
      defaultMaxAttempts: config.defaultMaxAttempts ?? 3,
      baseRetryDelayMs: config.baseRetryDelayMs ?? 20,
      defaultIdempotencyTtlMs: config.defaultIdempotencyTtlMs ?? 60_000,
      clock: config.clock ?? (() => Date.now()),
    };
  }

  start(): void {
    this.running = true;
    this.pump();
  }

  stop(): void {
    this.running = false;
  }

  enqueue(input: JobInput): EnqueueResult {
    const id = this.store.nextId();
    const record: JobRecord = {
      id,
      tenantId: input.tenantId,
      payload: input.payload,
      status: 'queued',
      attempts: 0,
      maxAttempts: input.maxAttempts ?? this.config.defaultMaxAttempts,
      idempotencyKey: input.idempotencyKey,
      idempotencyTtlMs: input.idempotencyTtlMs,
      createdAt: this.config.clock(),
    };
    this.store.save(record);
    this.queue.push(id);
    if (this.running) {
      this.pump();
    }
    return { jobId: id, deduplicated: false };
  }

  getJob(jobId: string): JobRecord | undefined {
    return this.store.get(jobId);
  }

  getDeadLetters(_tenantId?: string): JobRecord[] {
    return [];
  }

  replayDeadLetter(_jobId: string): { jobId: string } {
    throw new Error('Not implemented');
  }

  async drain(_opts?: DrainOptions): Promise<DrainResult> {
    throw new Error('Not implemented');
  }

  private pump(): void {
    while (this.running && this.activeCount < this.config.maxConcurrency && this.queue.length > 0) {
      const nextId = this.queue.shift()!;
      const job = this.store.get(nextId);
      if (!job || job.status !== 'queued') continue;
      this.executeJob(job);
    }
  }

  private executeJob(job: JobRecord): void {
    this.activeCount += 1;
    job.status = 'running';
    job.attempts += 1;
    const ac = new AbortController();

    runJobAttempt(job, this.handler, ac.signal).then((res) => {
      this.activeCount -= 1;
      if (res.ok) {
        job.status = 'succeeded';
        job.completedAt = this.config.clock();
      } else {
        job.lastError = res.error instanceof Error ? res.error.message : String(res.error);
        if (job.attempts < job.maxAttempts) {
          job.status = 'queued';
          const delay = computeBackoffMs(job.attempts, this.config.baseRetryDelayMs);
          setTimeout(() => {
            this.queue.push(job.id);
            if (this.running) this.pump();
          }, delay);
        } else {
          job.status = 'failed';
          job.failedAt = this.config.clock();
        }
      }
      if (this.running) {
        this.pump();
      }
    });
  }
}
""",
"src/index.ts": """
export * from './types.ts';
export * from './backoff.ts';
export * from './store.ts';
export * from './worker.ts';
export * from './dispatcher.ts';
""",
"test/dispatcher.test.ts": """
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { JobDispatcher } from '../src/index.ts';

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

describe('JobDispatcher baseline', () => {
  it('runs enqueued jobs and marks them succeeded', async () => {
    const processed: string[] = [];
    const d = new JobDispatcher(
      async (job) => {
        processed.push(String(job.payload));
      },
      { maxConcurrency: 2, baseRetryDelayMs: 5 },
    );
    d.start();
    const a = d.enqueue({ tenantId: 't1', payload: 'p1' });
    const b = d.enqueue({ tenantId: 't1', payload: 'p2' });
    await sleep(30);
    assert.deepEqual(processed.sort(), ['p1', 'p2']);
    assert.equal(d.getJob(a.jobId)?.status, 'succeeded');
    assert.equal(d.getJob(b.jobId)?.status, 'succeeded');
  });

  it('retries transient failure up to maxAttempts', async () => {
    let tries = 0;
    const d = new JobDispatcher(
      async () => {
        tries++;
        if (tries < 2) throw new Error('flaky');
      },
      { maxConcurrency: 1, baseRetryDelayMs: 10, defaultMaxAttempts: 3 },
    );
    d.start();
    const { jobId } = d.enqueue({ tenantId: 't1', payload: 'x' });
    await sleep(60);
    assert.equal(tries, 2);
    assert.equal(d.getJob(jobId)?.status, 'succeeded');
  });
});
"""
}

C2_GRADING = {
"hidden_grading.test.ts": """
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { JobDispatcher } from '../src/index.ts';

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

describe('C2 hidden grading suite', () => {
  it('1. idempotency deduplicates while queued and running within same tenant', async () => {
    let started = 0;
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });

    const d = new JobDispatcher(
      async () => {
        started++;
        await gate;
      },
      { maxConcurrency: 4 },
    );

    // Deduplicate while queued (before start)
    const r1 = d.enqueue({ tenantId: 't1', payload: 1, idempotencyKey: 'k1' });
    const r2 = d.enqueue({ tenantId: 't1', payload: 2, idempotencyKey: 'k1' });
    assert.equal(r1.deduplicated, false);
    assert.equal(r2.deduplicated, true);
    assert.equal(r2.jobId, r1.jobId);

    // Different tenant with same key is NOT deduplicated
    const rOther = d.enqueue({ tenantId: 't2', payload: 3, idempotencyKey: 'k1' });
    assert.equal(rOther.deduplicated, false);
    assert.notEqual(rOther.jobId, r1.jobId);

    d.start();
    await sleep(15);
    // Deduplicate while running
    const r3 = d.enqueue({ tenantId: 't1', payload: 4, idempotencyKey: 'k1' });
    assert.equal(r3.deduplicated, true);
    assert.equal(r3.jobId, r1.jobId);

    release();
    const dr = await d.drain({ timeoutMs: 500 });
    assert.equal(dr.drained, true);
    assert.equal(started, 2);
  });

  it('2. idempotency respects TTL using injected clock after succeeded', async () => {
    let now = 10_000;
    let runs = 0;
    const d = new JobDispatcher(
      async () => { runs++; },
      { maxConcurrency: 2, defaultIdempotencyTtlMs: 5000, clock: () => now },
    );
    d.start();

    const r1 = d.enqueue({ tenantId: 't1', payload: 'a', idempotencyKey: 'order-1' });
    await sleep(20);
    assert.equal(d.getJob(r1.jobId)?.status, 'succeeded');

    // Within TTL (10_000 + 4999 < 15_000)
    now = 14_999;
    const r2 = d.enqueue({ tenantId: 't1', payload: 'a', idempotencyKey: 'order-1' });
    assert.equal(r2.deduplicated, true);
    assert.equal(r2.jobId, r1.jobId);

    // At exact expiry boundary (now >= completedAt + ttlMs)
    now = 15_000;
    const r3 = d.enqueue({ tenantId: 't1', payload: 'a', idempotencyKey: 'order-1' });
    assert.equal(r3.deduplicated, false);
    assert.notEqual(r3.jobId, r1.jobId);

    await d.drain({ timeoutMs: 500 });
    assert.equal(runs, 2);
  });

  it('3. idempotency respects per-job custom idempotencyTtlMs', async () => {
    let now = 1000;
    const d = new JobDispatcher(
      async () => {},
      { maxConcurrency: 2, defaultIdempotencyTtlMs: 60_000, clock: () => now },
    );
    d.start();
    const r1 = d.enqueue({ tenantId: 't1', payload: 1, idempotencyKey: 'short', idempotencyTtlMs: 100 });
    await sleep(20);
    now = 1050;
    assert.equal(d.enqueue({ tenantId: 't1', payload: 1, idempotencyKey: 'short' }).deduplicated, true);
    now = 1100;
    const r2 = d.enqueue({ tenantId: 't1', payload: 1, idempotencyKey: 'short' });
    assert.equal(r2.deduplicated, false);
    assert.notEqual(r2.jobId, r1.jobId);
    await d.drain({ timeoutMs: 500 });
  });

  it('4. dead-lettered job releases idempotency key so a fresh job can be enqueued', async () => {
    let attempt = 0;
    const d = new JobDispatcher(
      async () => {
        attempt++;
        if (attempt === 1) {
          const e = Object.assign(new Error('fatal'), { nonRetryable: true });
          throw e;
        }
      },
      { maxConcurrency: 2, baseRetryDelayMs: 5 },
    );
    d.start();
    const r1 = d.enqueue({ tenantId: 't1', payload: 1, idempotencyKey: 'k-dead' });
    await sleep(25);
    assert.equal(d.getJob(r1.jobId)?.status, 'dead');

    const r2 = d.enqueue({ tenantId: 't1', payload: 2, idempotencyKey: 'k-dead' });
    assert.equal(r2.deduplicated, false);
    assert.notEqual(r2.jobId, r1.jobId);
    await d.drain({ timeoutMs: 500 });
    assert.equal(d.getJob(r2.jobId)?.status, 'succeeded');
  });

  it('5. per-tenant concurrency limit enforced without blocking other tenants', async () => {
    let globalActive = 0;
    let maxGlobalSeen = 0;
    const tenantActive: Record<string, number> = { A: 0, B: 0 };
    const tenantMax: Record<string, number> = { A: 0, B: 0 };
    const startOrder: string[] = [];

    const d = new JobDispatcher(
      async (job) => {
        globalActive++;
        maxGlobalSeen = Math.max(maxGlobalSeen, globalActive);
        tenantActive[job.tenantId] = (tenantActive[job.tenantId] ?? 0) + 1;
        tenantMax[job.tenantId] = Math.max(tenantMax[job.tenantId] ?? 0, tenantActive[job.tenantId]);
        startOrder.push(`${job.tenantId}:${job.payload}`);
        await sleep(30);
        tenantActive[job.tenantId]--;
        globalActive--;
      },
      { maxConcurrency: 3, maxConcurrencyPerTenant: 1 },
    );

    // Enqueue 5 jobs for Tenant A first, then 2 for Tenant B
    for (let i = 1; i <= 5; i++) d.enqueue({ tenantId: 'A', payload: i });
    for (let i = 1; i <= 2; i++) d.enqueue({ tenantId: 'B', payload: i });

    d.start();
    await d.drain({ timeoutMs: 2000 });

    assert.equal(tenantMax.A, 1, 'Tenant A exceeded per-tenant cap');
    assert.equal(tenantMax.B, 1, 'Tenant B exceeded per-tenant cap');
    assert.ok(maxGlobalSeen <= 3);
    assert.ok(maxGlobalSeen >= 2, 'Tenant B should have run concurrently with Tenant A');
    // Tenant B:1 must start in the first wave (index <= 1), not stuck behind all 5 of A!
    assert.ok(startOrder.indexOf('B:1') <= 1, `Head-of-line blocking detected: ${startOrder.join(',')}`);
  });

  it('6. round-robin fairness across tenants and FIFO within each tenant', async () => {
    const order: string[] = [];
    const d = new JobDispatcher(
      async (job) => {
        order.push(`${job.tenantId}:${job.payload}`);
        await sleep(5);
      },
      { maxConcurrency: 1, maxConcurrencyPerTenant: 1 },
    );

    // Enqueue bursty tenant A, then B, then C
    d.enqueue({ tenantId: 'A', payload: 1 });
    d.enqueue({ tenantId: 'A', payload: 2 });
    d.enqueue({ tenantId: 'A', payload: 3 });
    d.enqueue({ tenantId: 'B', payload: 1 });
    d.enqueue({ tenantId: 'B', payload: 2 });
    d.enqueue({ tenantId: 'C', payload: 1 });

    d.start();
    await d.drain({ timeoutMs: 2000 });

    // Round-robin: first round hits A:1, B:1, C:1 before A:2!
    assert.deepEqual(order.slice(0, 3), ['A:1', 'B:1', 'C:1']);
    // FIFO within A
    const aItems = order.filter((x) => x.startsWith('A:'));
    assert.deepEqual(aItems, ['A:1', 'A:2', 'A:3']);
    const bItems = order.filter((x) => x.startsWith('B:'));
    assert.deepEqual(bItems, ['B:1', 'B:2']);
  });

  it('7. tenant slot is released on error, retry-requeue, and dead-letter', async () => {
    let ranSecond = false;
    const d = new JobDispatcher(
      async (job) => {
        if (job.payload === 'fail') {
          throw new Error('boom');
        }
        ranSecond = true;
      },
      { maxConcurrency: 2, maxConcurrencyPerTenant: 1, defaultMaxAttempts: 2, baseRetryDelayMs: 40 },
    );
    d.start();
    const f = d.enqueue({ tenantId: 't1', payload: 'fail' });
    const g = d.enqueue({ tenantId: 't1', payload: 'good' });

    await d.drain({ timeoutMs: 1000 });
    assert.equal(ranSecond, true);
    assert.equal(d.getJob(g.jobId)?.status, 'succeeded');
    assert.equal(d.getJob(f.jobId)?.status, 'dead');
    assert.equal(d.getJob(f.jobId)?.attempts, 2);
  });

  it('8. nonRetryable error moves job straight to DLQ on attempt 1 without waiting for retries', async () => {
    let calls = 0;
    const d = new JobDispatcher(
      async () => {
        calls++;
        throw Object.assign(new Error('invalid payload'), { nonRetryable: true });
      },
      { maxConcurrency: 2, defaultMaxAttempts: 5, baseRetryDelayMs: 500 },
    );
    d.start();
    const start = Date.now();
    const { jobId } = d.enqueue({ tenantId: 't1', payload: 'bad' });
    const dr = await d.drain({ timeoutMs: 1000 });
    const elapsed = Date.now() - start;

    assert.equal(dr.drained, true);
    assert.equal(calls, 1);
    assert.ok(elapsed < 250, `Waited for backoff on nonRetryable error: ${elapsed}ms`);
    const rec = d.getJob(jobId)!;
    assert.equal(rec.status, 'dead');
    assert.equal(rec.attempts, 1);
    assert.match(rec.lastError ?? '', /invalid payload/);
    assert.ok(typeof rec.failedAt === 'number');
    assert.equal(d.getDeadLetters().length, 1);
    assert.equal(d.getDeadLetters('t1').length, 1);
    assert.equal(d.getDeadLetters('t2').length, 0);
  });

  it('9. replayDeadLetter resets attempts, removes from DLQ, and re-executes cleanly', async () => {
    let shouldFail = true;
    let execCount = 0;
    const d = new JobDispatcher(
      async () => {
        execCount++;
        if (shouldFail) throw new Error('down');
      },
      { maxConcurrency: 2, defaultMaxAttempts: 2, baseRetryDelayMs: 5 },
    );
    d.start();
    const { jobId } = d.enqueue({ tenantId: 't1', payload: 'hello', idempotencyKey: 'rep-1' });
    await sleep(60);

    assert.equal(d.getJob(jobId)?.status, 'dead');
    assert.equal(d.getDeadLetters('t1').length, 1);
    assert.equal(execCount, 2);

    // Replaying unknown or non-dead job throws
    assert.throws(() => d.replayDeadLetter('job_nonexistent'));

    shouldFail = false;
    const rep = d.replayDeadLetter(jobId);
    assert.equal(rep.jobId, jobId);
    assert.equal(d.getDeadLetters('t1').length, 0);

    await d.drain({ timeoutMs: 500 });
    const rec = d.getJob(jobId)!;
    assert.equal(rec.status, 'succeeded');
    assert.equal(rec.attempts, 1);
    assert.equal(execCount, 3);
    assert.throws(() => d.replayDeadLetter(jobId));
  });

  it('10. drain() rejects new enqueues, waits for queued+running+retrying jobs, resolves drained:true', async () => {
    let tries = 0;
    const done: string[] = [];
    const d = new JobDispatcher(
      async (job) => {
        if (job.payload === 'flaky' && tries === 0) {
          tries++;
          throw new Error('once');
        }
        await sleep(20);
        done.push(String(job.payload));
      },
      { maxConcurrency: 1, baseRetryDelayMs: 15, defaultMaxAttempts: 3 },
    );
    d.start();
    d.enqueue({ tenantId: 't1', payload: 'flaky' });
    d.enqueue({ tenantId: 't1', payload: 'second' });

    const drainPromise = d.drain({ timeoutMs: 1000 });
    assert.throws(() => d.enqueue({ tenantId: 't1', payload: 'late' }), /draining/i);

    const res = await drainPromise;
    assert.equal(res.drained, true);
    assert.deepEqual(res.cancelled, []);
    assert.deepEqual(done.sort(), ['flaky', 'second']);
  });

  it('11. drain({ timeoutMs }) aborts running jobs, cancels queued & retry-waiting jobs, clears timers', async () => {
    let sawAbort = false;
    const d = new JobDispatcher(
      async (job, signal) => {
        if (job.payload === 'hang') {
          await new Promise<void>((resolve) => {
            signal.addEventListener('abort', () => {
              sawAbort = true;
              resolve();
            }, { once: true });
          });
        } else if (job.payload === 'retryLong') {
          throw new Error('fail-then-long-backoff');
        }
      },
      { maxConcurrency: 2, maxConcurrencyPerTenant: 1, baseRetryDelayMs: 5000, defaultMaxAttempts: 3 },
    );
    d.start();
    const jHang = d.enqueue({ tenantId: 't1', payload: 'hang' });
    const jRetry = d.enqueue({ tenantId: 't2', payload: 'retryLong' });
    const jQueued = d.enqueue({ tenantId: 't1', payload: 'queuedBehindHang' });
    await sleep(25);

    const start = Date.now();
    const res = await d.drain({ timeoutMs: 60 });
    const elapsed = Date.now() - start;

    assert.equal(res.drained, false);
    assert.equal(sawAbort, true);
    assert.ok(elapsed < 400, `drain hung waiting for retry timer: ${elapsed}ms`);
    assert.ok(res.cancelled.includes(jHang.jobId), 'running hanging job should be cancelled');
    assert.ok(res.cancelled.includes(jRetry.jobId), 'retry-waiting job should be cancelled');
    assert.ok(res.cancelled.includes(jQueued.jobId), 'queued job behind hang should be cancelled');
    assert.equal(d.getJob(jHang.jobId)?.status, 'cancelled');
    assert.equal(d.getJob(jRetry.jobId)?.status, 'cancelled');
    assert.equal(d.getJob(jQueued.jobId)?.status, 'cancelled');
  });

  it('12. drain() on idle dispatcher resolves immediately', async () => {
    const d = new JobDispatcher(async () => {}, { maxConcurrency: 2 });
    d.start();
    const start = Date.now();
    const res = await d.drain({ timeoutMs: 500 });
    assert.equal(res.drained, true);
    assert.deepEqual(res.cancelled, []);
    assert.ok(Date.now() - start < 100);
  });

  it('13. enqueue without idempotencyKey always creates distinct jobs', async () => {
    const d = new JobDispatcher(async () => {}, { maxConcurrency: 2 });
    const a = d.enqueue({ tenantId: 't1', payload: 'same' });
    const b = d.enqueue({ tenantId: 't1', payload: 'same' });
    assert.equal(a.deduplicated, false);
    assert.equal(b.deduplicated, false);
    assert.notEqual(a.jobId, b.jobId);
  });
});
"""
}

def main():
    parser = argparse.ArgumentParser(description="Build C1 and C2 fixer-bench templates and grading suites")
    parser.add_argument("--work-dir", default="/tmp/opencode/fixer-bench", help="Benchmark work directory")
    args = parser.parse_args()
    base = pathlib.Path(args.work_dir)

    write_files(base / "templates" / "c1-refactor-ts", C1_FILES)
    git_init(base / "templates" / "c1-refactor-ts")
    write_files(base / "grading" / "c1-refactor-ts", C1_GRADING)

    write_files(base / "templates" / "c2-feature-ts", C2_FILES)
    git_init(base / "templates" / "c2-feature-ts")
    write_files(base / "grading" / "c2-feature-ts", C2_GRADING)

    print("Built C1 and C2 successfully.")


if __name__ == "__main__":
    main()
