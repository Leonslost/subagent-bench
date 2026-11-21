# `@fixer` Benchmark Suite Reference

5 multi-file engineering challenges across TypeScript, Python, and Go with **72 hidden held-out tests**, `10×` Go `-race` concurrency stress, and 5 adversarial MVCC/GC deep probes.

## Prerequisites
- `node` (v22+ with native TypeScript stripping for `node --test`)
- `python3` (stdlib `unittest`, `decimal`, `sqlite3`)
- `go` (with `-race` detector)
- `git`

## Scaffold & Prepare Commands

```bash
WORK=/tmp/opencode/fixer-bench
SCRIPTS=<skill_dir>/scripts/fixer

# 1. Generate all 5 challenge templates + hidden grading suites
python3 "$SCRIPTS/bench_tools.py" build --work-dir "$WORK"

# 2. Clone isolated git workspaces for your candidate config slugs
python3 "$SCRIPTS/bench_tools.py" prepare \
  --work-dir "$WORK" \
  --configs "cfg-a,cfg-b,cfg-c,cfg-d"
```

Isolated workspaces are created at `<work-dir>/runs/<challenge>/<cfg>/`. Hidden grading tests live separately under `<work-dir>/grading/<challenge>/` and are NEVER visible inside `runs/`.

## Execution Strategy
- **Parallel waves work well** because every run has its own git repo and zero shared MCP state. Dispatch 4–8 `@fixer` subagents in parallel per wave (e.g., all configs for one challenge at a time).
- Pass `agent: "fixer"` and `model: "<provider/model#variant>"` explicitly on every `subagent()` call.
- Record each returned `sessionID` into `<work-dir>/sessions.json` (`{ "<challenge>": { "<cfg>": "<session_id>" } }`).

## Automated Grading & Deep Probes

```bash
# Grade a single run
python3 "$SCRIPTS/bench_tools.py" grade c1-refactor-ts cfg-a \
  --work-dir "$WORK" \
  --session-id <sid>

# Grade the entire matrix + run Go -race stress + C5 adversarial probes + telemetry
python3 "$SCRIPTS/bench_tools.py" grade-all \
  --work-dir "$WORK" \
  --sessions "$WORK/sessions.json" \
  --out "$WORK/final_results.json" \
  --stress-runs 10
```

### Challenge & Hidden Test Matrix
| Challenge | Lang | Files | Hidden Tests | Extra Automated Checks | What It Differentiates |
|---|---|---:|---:|---|---|
| `c1-refactor-ts` | TypeScript | 10 | 19 | Visible + hidden `node --test` | Cross-file mechanical refactor discipline, `Result<T, AppError>`, `AbortSignal`/timer cleanup, legacy shim |
| `c2-feature-ts` | TypeScript | 7 | 13 | Visible + hidden `node --test` + module-boundary diff audit | Multi-file feature architecture (`store.ts` vs `dispatcher.ts`), clock-injected TTL, round-robin fairness, graceful drain |
| `c3-bugfix-py` | Python | 7 | 16 | Visible + hidden `unittest` | Interacting financial invariants: month-end anchor drift, Hamilton cent allocation, `Decimal ROUND_HALF_UP`, preview purity |
| `c4-concurrent-go` | Go | 6 | 10 | `go test -race -count=10 ./...` (visible + hidden) | Concurrency safety, slot release during retry backoff, `FailFast` goroutine draining, race-free `EventSink` |
| `c5-mvcc-kv-ts` | TypeScript | 6 | 14 | 5 deep probes (`P1–P3` + `Q1` live `totalKeys` + `Q2` multi-snapshot intermediate pruning) | Under-specified systems invariants, Snapshot Isolation, First-Committer-Wins, nested savepoints, GC compaction |

---

## Verbatim Prompts (Replace `<WORK>` and `<CFG>` Only)

### C1 — `c1-refactor-ts`
```text
Workspace: `<WORK>/runs/c1-refactor-ts` -> ONLY read/edit files inside `<WORK>/runs/c1-refactor-ts/<CFG>`.

Task: Refactor `mini-rpc` across `src/errors.ts`, `src/types.ts`, `src/context.ts`, `src/router.ts`, `src/middleware/{auth,rateLimit,validate,logging}.ts`, `src/adapters/http.ts`, `src/client.ts`, and `test/rpc.test.ts` from exception-based error handling to structured `Result<T, AppError>` + `AbortSignal` propagation.

Requirements:
1. `src/errors.ts`:
   - Export `ErrorCode = 'VALIDATION_ERROR' | 'UNAUTHORIZED' | 'FORBIDDEN' | 'NOT_FOUND' | 'RATE_LIMITED' | 'TIMEOUT' | 'CANCELLED' | 'INTERNAL'`.
   - Export `AppError` (`{ code: ErrorCode; message: string; retryable: boolean; details?: Record<string, unknown>; cause?: unknown }`).
   - Export `createAppError(code: ErrorCode, message: string, opts?: { retryable?: boolean; details?: Record<string, unknown>; cause?: unknown }): AppError`. Default `retryable` to `true` for `'RATE_LIMITED'` and `'TIMEOUT'`, `false` otherwise unless overridden in `opts`.
   - Export `toAppError(err: unknown): AppError`: if `err` is already an `AppError`, return it as-is; if `err` is an `AbortError` (Error/DOMException with `name === 'AbortError'`), map to `CANCELLED` (`retryable: false`); otherwise map to `INTERNAL` (`retryable: false`, preserving error message & `cause`).
2. `src/types.ts`:
   - Export `Result<T, E = AppError> = { ok: true; value: T } | { ok: false; error: E }`, plus `ok<T>(value: T): Result<T, never>` and `err<E = AppError>(error: E): Result<never, E>`.
   - Add `signal: AbortSignal` to `HandlerContext`.
   - Update `RpcHandler` and `Middleware` (`next` and return values) to return `Promise<Result<unknown, AppError>>`.
3. `src/context.ts`:
   - Support optional `{ signal?: AbortSignal; timeoutMs?: number }` when creating a context.
   - Combine external `signal` and `timeoutMs` cleanly so whichever fires first aborts `ctx.signal`, while distinguishing timeout (`TIMEOUT`, retryable: `true`) vs external abort (`CANCELLED`, retryable: `false`).
   - Provide cleanup so timers and abort listeners never leak.
4. `src/router.ts`:
   - Update `dispatch(req: RpcRequest, opts?: { signal?: AbortSignal; timeoutMs?: number }): Promise<Result<unknown, AppError>>`.
   - Never reject the returned promise: catch any unexpected thrown error from middleware or handler and convert via `toAppError` into `err(...)`.
   - If `opts?.signal?.aborted` is already true before dispatch, immediately return `err(createAppError('CANCELLED', ...))` without running middlewares or handler.
   - Race execution against abort/timeout so if timeout or external abort fires while pending, `dispatch` settles immediately with `TIMEOUT` (`retryable: true`) or `CANCELLED` (`retryable: false`), aborts `ctx.signal`, and cleans up all timers/listeners.
   - Unknown method returns `err(createAppError('NOT_FOUND', ..., { retryable: false }))`.
5. Middlewares (`src/middleware/*.ts`):
   - `auth.ts`: return `err(...)` instead of throwing (`UNAUTHORIZED` for missing/invalid bearer token, `FORBIDDEN` for missing scope; both `retryable: false`).
   - `rateLimit.ts`: return `err(createAppError('RATE_LIMITED', ..., { retryable: true, details: { retryAfterMs } }))` instead of throwing.
   - `validate.ts`: return `err(createAppError('VALIDATION_ERROR', ..., { retryable: false, details: { fields } }))` instead of throwing.
   - `logging.ts`: log `{ method, ok: true, durationMs }` (omit `code`) on `ok`, and `{ method, ok: false, code: appError.code, durationMs }` on both returned `err(...)` results AND unexpected thrown exceptions (converting thrown errors via `toAppError` and returning `err(...)` without swallowing the error).
6. `src/adapters/http.ts`:
   - Map `ErrorCode` to HTTP status: `VALIDATION_ERROR: 400`, `UNAUTHORIZED: 401`, `FORBIDDEN: 403`, `NOT_FOUND: 404`, `TIMEOUT: 408`, `RATE_LIMITED: 429`, `CANCELLED: 499`, `INTERNAL: 500`.
   - Add optional `signal?: AbortSignal; timeoutMs?: number` to `HttpRequest` and forward them to `router.dispatch`.
   - `createHttpAdapter`: return `{ status: 200, body: { ok: true, data: res.value } }` on `ok`, and `{ status, body: { ok: false, error: { code, message, retryable, details } } }` on `err`.
   - `createLegacyHandler`: backwards-compatibility shim returning `{ status: 200, data: res.value }` on `ok` and `{ status, error: res.error.message }` on `err` without throwing.
7. `src/client.ts`:
   - Add optional `timeoutMs?: number; signal?: AbortSignal` to `CallOptions`.
   - `RpcClient.call(...)` returns `Promise<Result<unknown, AppError>>`, forwarding `timeoutMs` and `signal` on each attempt.
   - Retry up to `maxRetries` (default `0`) ONLY when `!res.ok && res.error.retryable === true`. Never retry non-retryable errors.
   - If `opts.signal` aborts before or during retry backoff wait (`retryDelayMs`), clear the timer immediately and return `err(createAppError('CANCELLED', ..., { retryable: false }))`.
8. Update `test/rpc.test.ts` to match the refactored `Result` API and cover the new behavior.

Validation (focused): Run `node --test test/rpc.test.ts` inside `<WORK>/runs/c1-refactor-ts/<CFG>` and ensure all tests pass with clean exit.
```

### C2 — `c2-feature-ts`
```text
Workspace: ONLY read/edit files inside `<WORK>/runs/c2-feature-ts/<CFG>`.

Task: Extend `job-dispatch` across `src/types.ts`, `src/store.ts`, `src/backoff.ts`, `src/worker.ts`, `src/dispatcher.ts`, and `test/dispatcher.test.ts` to implement idempotency keys with TTL, per-tenant concurrency limits with round-robin fairness, dead-letter queue + replay, and graceful drain with timeout/cancellation.

Requirements:
1. **Idempotency Keys with TTL**:
   - Scoped per `(tenantId, idempotencyKey)` (different tenants using the same key are independent).
   - `enqueue(input)` without `idempotencyKey` always creates a new job (`{ jobId, deduplicated: false }`).
   - If an existing job for `(tenantId, idempotencyKey)` is currently `queued` or `running` (including waiting on a retry timer), OR is `succeeded` and not expired (`clock() < completedAt + ttlMs`, where `ttlMs = existing.idempotencyTtlMs ?? config.defaultIdempotencyTtlMs`), return `{ jobId: existing.id, deduplicated: true }` without creating a duplicate job.
   - If the previous job for that key is `dead` or `cancelled`, OR is `succeeded` and expired (`clock() >= completedAt + ttlMs`), create a fresh job (`deduplicated: false`) and update the `(tenantId, idempotencyKey)` mapping to the new job.
   - Always use the configured `clock()` (never raw `Date.now()` directly) for timestamps and TTL checks.
2. **Per-Tenant Concurrency Limits & Cross-Tenant Fairness**:
   - Enforce both global `config.maxConcurrency` and per-tenant `config.maxConcurrencyPerTenant` (default `Infinity`).
   - No head-of-line blocking: if Tenant A is at its `maxConcurrencyPerTenant` limit, ready jobs from Tenant B MUST still dispatch immediately whenever global capacity is available.
   - Among eligible tenants (ready queued jobs and below per-tenant cap), schedule **round-robin** across tenants while preserving **FIFO** order within each tenant.
   - Always release both global and per-tenant active slots when an attempt ends (success, retry-requeue, dead-letter, or cancellation).
3. **Dead-Letter Queue (DLQ) & Replay**:
   - Move a job to `status = 'dead'` (recording `lastError` and `failedAt = clock()`) and into the DLQ when either:
     - `runJobAttempt` returns `nonRetryable: true` (immediately on that attempt — do NOT retry or wait for backoff), OR
     - `job.attempts >= job.maxAttempts`.
   - `getDeadLetters(tenantId?: string): JobRecord[]`: returns all jobs currently in the DLQ (filtered by `tenantId` if provided).
   - `replayDeadLetter(jobId: string): { jobId: string }`: throw an `Error` if `jobId` is not currently in the DLQ; otherwise remove it from DLQ, reset `attempts = 0`, `status = 'queued'`, clear `failedAt`/`lastError`, re-enqueue into its tenant queue (keeping its `idempotencyKey` active if present), trigger scheduling if running, and return `{ jobId }`.
4. **Graceful Drain with Timeout & Cancellation** (`drain(opts?: DrainOptions): Promise<DrainResult>`):
   - Marks dispatcher as draining: subsequent `enqueue(...)` calls MUST throw `Error('Dispatcher is draining')`.
   - If already idle (no running jobs, no queued jobs, no pending retry timers), resolve immediately with `{ drained: true, cancelled: [] }`.
   - Otherwise wait for all currently queued, running, and retry-waiting jobs to finish (`succeeded` or `dead`). If all finish before `opts?.timeoutMs` (or if `timeoutMs` is omitted), clear any drain timeout timer and resolve with `{ drained: true, cancelled: [] }`.
   - If `opts?.timeoutMs` expires while jobs remain running, queued, or waiting for retry:
     - Clear all pending retry timers (no dangling timers!),
     - Abort the `AbortSignal` of every running job,
     - Mark every unfinished job (running, queued, and retry-waiting) as `status = 'cancelled'` (and prevent late completions of aborted running jobs from overwriting `'cancelled'` or scheduling retries),
     - Resolve with `{ drained: false, cancelled: [...] }` containing all cancelled job IDs.
5. Keep existing tests in `test/dispatcher.test.ts` passing and add focused tests covering these features.

Validation (focused): Run `node --test test/dispatcher.test.ts` inside `<WORK>/runs/c2-feature-ts/<CFG>` and ensure all tests pass with clean exit.
```

### C3 — `c3-bugfix-py`
```text
Workspace: ONLY read/edit files inside `<WORK>/runs/c3-bugfix-py/<CFG>`.

Task: Fix 4 cross-file bugs in the `subbill` subscription billing engine (`subbill/dates.py`, `subbill/proration.py`, `subbill/tax.py`, `subbill/coupons.py`, `subbill/billing.py`, and update/expand `tests/test_billing.py`).

Bug Reports & Required Behavior:
1. **Month-end billing anchor drift (`subbill/dates.py`)**:
   - Currently advancing month-by-month loses the original `start_date.day` after shorter months (e.g., Jan 31 -> Feb 28 -> Mar 28).
   - Fix `billing_date_for_cycle(start_date, cycle_index)` so every cycle advances directly by `cycle_index` months from `start_date` and clamps `start_date.day` to the target month's last day (preserving Jan 31 -> Feb 28 -> Mar 31 -> Apr 30 -> ... -> leap Feb 29 -> Mar 31; and Feb 29 -> Mar 29 -> non-leap Feb 28 -> leap Feb 29).
2. **Cent conservation, exact rounding, and post-discount tax (`subbill/proration.py`, `subbill/tax.py`, `subbill/billing.py`)**:
   - `allocate_amount(total_cents, weights)`: currently drops remainder cents. Implement exact largest-remainder (Hamilton) allocation so `sum(result) == total_cents` always, breaking remainder ties by lowest index. Handle negative `total_cents` symmetrically (allocate `abs(total_cents)` and negate each element), `total_cents == 0`, zero weights (when total weight > 0), and empty `weights -> []`.
   - `prorate_cents(full_amount_cents, days_used, total_days)`: replace float `round()` with exact `Decimal` arithmetic using `ROUND_HALF_UP` (half away from zero).
   - `calculate_tax_cents(net_amount_cents, tax_rate_bps)`: return `0` if `net_amount_cents <= 0` or `tax_rate_bps == 0`; raise `ValueError` if `tax_rate_bps < 0`; use exact `Decimal` arithmetic with `ROUND_HALF_UP` (`net_amount_cents * tax_rate_bps / 10000`).
   - In `billing.py`, calculate tax on the **post-discount** net subtotal, not the pre-discount subtotal.
3. **Coupon stacking order, compounding, cap, and dry-run mutation (`subbill/coupons.py`)**:
   - Never mutate the caller's `coupons` sequence.
   - If `subtotal_cents <= 0`, apply no coupons (`discount_cents=0`, `net_subtotal_cents=subtotal_cents`, `applied_codes=[]`) and do not increment `times_redeemed`.
   - Filter to eligible coupons: `currency` matches, `expires_at is None or invoice_date <= expires_at`, and `max_redemptions is None or times_redeemed < max_redemptions`.
   - Apply eligible `percent_off` coupons first, sorted by `(-percent_off, code)`, each compounding sequentially on the current remaining subtotal using exact `Decimal` `ROUND_HALF_UP`.
   - Then apply eligible `amount_off` coupons sorted by `code`, deducting `min(remaining, amount_off)`.
   - Stop once `remaining == 0` — coupons that would contribute 0 discount must NOT be included in `applied_codes` and must NOT increment `times_redeemed`.
   - Total discount can never exceed `subtotal_cents`.
   - When `preview=True`, NEVER increment `coupon.times_redeemed`.
4. **Negative invoice credit rollover, preview purity, and idempotent credit notes (`subbill/billing.py`)**:
   - In `generate_invoice(..., preview=False)`:
     - When `preview=True`, do NOT mutate `account.credit_balance_cents`, `account.invoices`, `account._invoice_seq`, or any `coupon.times_redeemed`.
     - Only apply coupons when `subtotal > 0`. Compute tax on `post_discount = subtotal - discount_cents` (0 tax if `post_discount <= 0`). `total = post_discount + tax`.
     - If `total < 0` (e.g., mid-cycle downgrade surplus): set `credit_applied_cents = 0`, `amount_due_cents = 0`, and when `not preview`, add `-total` to `account.credit_balance_cents`.
     - If `total >= 0`: `credit_applied_cents = min(account.credit_balance_cents, total)`, `amount_due_cents = total - credit_applied_cents`, and when `not preview`, subtract `credit_applied_cents` from `account.credit_balance_cents`.
   - In `apply_credit_note(account, invoice, credit_id, amount_cents)`:
     - Validate `amount_cents > 0`, else raise `ValueError`.
     - Idempotent by `credit_id` on `account.credit_notes`: if `credit_id` already exists, return the existing `CreditNote` with zero side effects.
     - Enforce refundable cap: sum existing credit notes on `invoice.id`; if `amount_cents > max(0, invoice.total_cents) - already_credited`, raise `ValueError`.
     - Do not double-credit: reduce `invoice.amount_due_cents` first by `applied_to_due = min(invoice.amount_due_cents, amount_cents)`, and add ONLY the overflow (`amount_cents - applied_to_due`) to `account.credit_balance_cents`. Record and return `CreditNote`.
5. Keep existing tests in `tests/test_billing.py` passing and add unit tests covering all 4 bug fixes.

Validation (focused): Run `python3 -m unittest discover -s tests` inside `<WORK>/runs/c3-bugfix-py/<CFG>` and ensure all tests pass.
```

### C4 — `c4-concurrent-go`
```text
Workspace: ONLY read/edit files inside `<WORK>/runs/c4-concurrent-go/<CFG>`.

Task: Replace the sequential stub in `dagrun` (`graph.go`, `events.go`, `runner.go`, `runner_test.go`) with a race-free concurrent DAG task runner.

Requirements:
1. **Graph Validation (`graph.go`)**:
   - `Validate(tasks []Task) error` must detect: empty task IDs (`ErrEmptyTaskID`), duplicate task IDs (`ErrDuplicateTask`), dependencies referencing unknown task IDs (`ErrMissingDependency`), and self-dependencies or multi-node cycles (`ErrCycleDetected`).
   - Do not mutate input `tasks` or their `Deps` slices. Handle duplicate entries within a task's own `Deps` slice cleanly during scheduling.
2. **Concurrent DAG Execution (`runner.go`)**:
   - `Run(ctx context.Context, tasks []Task, opts Options) (*RunResult, error)`:
     - Validate first via `Validate(tasks)`; on error return `nil, err` immediately without executing any task.
     - Empty `tasks` returns `&RunResult{Tasks: map[string]*TaskResult{}}, nil`.
     - Run each task only after all of its `Deps` have succeeded, regardless of input slice ordering (e.g., reverse topological order).
     - Enforce `opts.MaxConcurrency` (if `<= 0`, unlimited): never execute more than `opts.MaxConcurrency` task functions simultaneously.
3. **Per-Task Timeout & Retries**:
   - Execute up to `1 + task.MaxRetries` attempts.
   - If `task.Timeout > 0`, wrap each attempt with a fresh `context.WithTimeout` derived from the run context (cleanly cancelling it when the attempt returns).
   - Between failed attempts, wait `task.RetryDelay` while respecting run-context cancellation immediately (never sleep past cancel; never start a retry if the run context is already cancelled).
   - Release the concurrency slot while waiting in `RetryDelay` and re-acquire a slot before the next attempt so retrying tasks do not block other ready tasks.
4. **Failure Modes & Cancellation**:
   - `opts.FailFast == true`: on the first permanent task failure (retries exhausted), cancel the internal run context so in-flight tasks see cancellation, mark already-started/retrying tasks aborted by cancellation as `StatusCancelled`, mark unstarted tasks as `StatusSkipped`, and wait for ALL in-flight goroutines to finish before `Run` returns (zero goroutine leaks).
   - `opts.FailFast == false` (continue-on-error): when a task permanently fails, mark all of its transitive dependents as `StatusSkipped` (never execute them) while allowing all independent branches to run to completion.
   - If caller `ctx` is cancelled: abort in-flight/retrying tasks (`StatusCancelled`), skip unstarted tasks (`StatusSkipped`), and wait for all goroutines to exit before returning.
5. **Events & Results (`events.go`, `runner.go`)**:
   - Every task in `tasks` MUST be recorded in `RunResult.Tasks[id]` with accurate `ID`, `Status`, `Attempts`, `Output`, `Err`, and `Duration`.
   - If `opts.Sink != nil`, serialize all `opts.Sink.Emit(Event)` calls internally so non-thread-safe sinks (like `RecordingSink`) are completely race-free under `go test -race`.
   - Emit `EventStarted` (1-based `Attempt`) for each attempt, `EventRetrying` after a failed attempt that will be retried, and one terminal event per task (`EventSucceeded`, `EventFailed`, `EventSkipped`, or `EventCancelled`).
   - Return `nil` error iff all tasks succeeded; otherwise return a non-nil error.
6. Preserve existing tests in `runner_test.go` and add unit tests covering validation, concurrency, retries, timeouts, slot release, fail-fast, continue-on-error, and cancellation.

Validation (focused): Run `go test -race ./...` inside `<WORK>/runs/c4-concurrent-go/<CFG>` and ensure all tests pass with zero races.
```

### C5 — `c5-mvcc-kv-ts`
```text
Workspace: ONLY read/edit files inside `<WORK>/runs/c5-mvcc-kv-ts/<CFG>`.

Task: Replace the naive single-version placeholder in `mvcc-kv` (`src/version_store.ts`, `src/tx.ts`, `src/store.ts`, `test/kv.test.ts`, keeping `src/types.ts` contracts intact) with a full in-memory MVCC key-value store supporting Snapshot Isolation, First-Committer-Wins conflict detection, nested savepoints, snapshot-consistent range scans, and safe garbage-collection compaction.

Requirements:
1. **MVCC Snapshot Isolation**:
   - `begin()` creates an active transaction with `startTs` equal to the store's current monotonic timestamp.
   - Reads (`get`, `scan`) observe all versions committed at `commitTs <= startTs` merged with the transaction's own uncommitted writes/deletes. Uncommitted changes are invisible to other transactions and discarded on `rollback()`.
   - Calling transaction operations (`get`, `set`, `delete`, `scan`, `savepoint`, `rollbackTo`, `releaseSavepoint`, `commit`) on an already committed or aborted transaction throws an `Error`.
2. **First-Committer-Wins Conflict Detection & Atomic Commit**:
   - On `commit()`, detect write-write conflicts: if any key in the transaction's effective write set (sets or deletes) has been committed by another transaction with `commitTs > tx.startTs`, abort the transaction (`status = 'aborted'`) and throw `ConflictError(conflictingKey)` atomically (no partial writes applied).
   - Disjoint concurrent writers and read-only transactions commit cleanly without false conflicts. On commit with writes, advance the store's monotonic timestamp and publish new versions/tombstones at that `commitTs`, returning the commit timestamp.
3. **Nested Named Savepoints (SQL semantics)**:
   - `savepoint(name)`: push a named savepoint (duplicate names shadow outer savepoints; most recent matches first).
   - `rollbackTo(name)`: restore transaction state to that savepoint, discarding inner savepoints created after it while keeping `name` itself active. Throw `Error` if `name` does not exist.
   - `releaseSavepoint(name)`: commit its changes into the enclosing scope and remove `name` and any inner savepoints. Throw `Error` if `name` does not exist.
4. **Range Scans (`scan(opts?)`)**:
   - Return `ScanEntry[]` sorted lexicographically by `key`, respecting optional `start` (inclusive), `end` (exclusive), `prefix`, and `limit`, accurately reflecting snapshot state merged with uncommitted inserts, updates, and deletes.
5. **Compaction & Stats (`compact()`, `stats()`)**:
   - `compact()` prunes obsolete historical versions and unreachable tombstones that cannot be observed by any currently active transaction, without breaking any open snapshot's reads/scans, returning `{ removedVersions }`.
   - Keep `stats()` (`activeTransactions`, `currentTimestamp`, `totalKeys`, `totalVersions`) accurate across commits, deletes, and compaction.
6. Preserve baseline tests in `test/kv.test.ts` and add focused tests covering isolation, conflicts, savepoints, scans, and compaction.

Validation (focused): Run `node --test test/kv.test.ts` inside `<WORK>/runs/c5-mvcc-kv-ts/<CFG>` and ensure all tests pass.
```
