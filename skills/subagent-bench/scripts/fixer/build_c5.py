#!/usr/bin/env python3
import argparse
import subprocess, pathlib, shutil

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

C5_FILES = {
"package.json": """
{
  "name": "mvcc-kv",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "test": "node --test test/kv.test.ts"
  }
}
""",
"src/types.ts": """
export type TxStatus = 'active' | 'committed' | 'aborted';

export interface ScanOptions {
  start?: string;   // inclusive
  end?: string;     // exclusive
  prefix?: string;
  limit?: number;
}

export interface ScanEntry {
  key: string;
  value: string;
}

export interface StoreStats {
  activeTransactions: number;
  currentTimestamp: number;
  totalKeys: number;
  totalVersions: number;
}

export class ConflictError extends Error {
  readonly key: string;
  constructor(key: string, message?: string) {
    super(message ?? `Write-write conflict on key "${key}"`);
    this.name = 'ConflictError';
    this.key = key;
  }
}

export interface Transaction {
  readonly id: number;
  readonly startTs: number;
  readonly status: TxStatus;
  get(key: string): string | undefined;
  set(key: string, value: string): void;
  delete(key: string): void;
  scan(opts?: ScanOptions): ScanEntry[];
  savepoint(name: string): void;
  rollbackTo(name: string): void;
  releaseSavepoint(name: string): void;
  commit(): number;
  rollback(): void;
}
""",
"src/version_store.ts": """
// Naive single-version storage placeholder (needs MVCC version chains + tombstones + GC).
export class VersionStore {
  private data = new Map<string, string>();

  getLatest(key: string): string | undefined {
    return this.data.get(key);
  }

  put(key: string, value: string): void {
    this.data.set(key, value);
  }

  remove(key: string): void {
    this.data.delete(key);
  }

  keys(): string[] {
    return Array.from(this.data.keys());
  }

  totalKeys(): number {
    return this.data.size;
  }

  totalVersions(): number {
    return this.data.size;
  }
}
""",
"src/tx.ts": """
import type { ScanEntry, ScanOptions, Transaction, TxStatus } from './types.ts';
import type { VersionStore } from './version_store.ts';

export class NaiveTransaction implements Transaction {
  readonly id: number;
  readonly startTs: number;
  status: TxStatus = 'active';
  private store: VersionStore;
  private onFinish: (tx: NaiveTransaction) => void;

  constructor(
    id: number,
    startTs: number,
    store: VersionStore,
    onFinish: (tx: NaiveTransaction) => void,
  ) {
    this.id = id;
    this.startTs = startTs;
    this.store = store;
    this.onFinish = onFinish;
  }

  get(key: string): string | undefined {
    return this.store.getLatest(key);
  }

  set(key: string, value: string): void {
    this.store.put(key, value);
  }

  delete(key: string): void {
    this.store.remove(key);
  }

  scan(opts: ScanOptions = {}): ScanEntry[] {
    const out: ScanEntry[] = [];
    for (const key of this.store.keys().sort()) {
      if (opts.start !== undefined && key < opts.start) continue;
      if (opts.end !== undefined && key >= opts.end) continue;
      if (opts.prefix !== undefined && !key.startsWith(opts.prefix)) continue;
      const value = this.store.getLatest(key);
      if (value !== undefined) out.push({ key, value });
      if (opts.limit !== undefined && out.length >= opts.limit) break;
    }
    return out;
  }

  savepoint(_name: string): void {
    throw new Error('Not implemented');
  }

  rollbackTo(_name: string): void {
    throw new Error('Not implemented');
  }

  releaseSavepoint(_name: string): void {
    throw new Error('Not implemented');
  }

  commit(): number {
    this.status = 'committed';
    this.onFinish(this);
    return this.startTs + 1;
  }

  rollback(): void {
    this.status = 'aborted';
    this.onFinish(this);
  }
}
""",
"src/store.ts": """
import { NaiveTransaction } from './tx.ts';
import { VersionStore } from './version_store.ts';
import type { StoreStats, Transaction } from './types.ts';

export class KVStore {
  private readonly versions = new VersionStore();
  private readonly active = new Set<Transaction>();
  private txSeq = 0;
  private ts = 0;

  begin(): Transaction {
    const id = ++this.txSeq;
    const tx = new NaiveTransaction(id, this.ts, this.versions, (finished) => {
      this.active.delete(finished);
    });
    this.active.add(tx);
    return tx;
  }

  compact(): { removedVersions: number } {
    return { removedVersions: 0 };
  }

  stats(): StoreStats {
    return {
      activeTransactions: this.active.size,
      currentTimestamp: this.ts,
      totalKeys: this.versions.totalKeys(),
      totalVersions: this.versions.totalVersions(),
    };
  }
}
""",
"src/index.ts": """
export * from './types.ts';
export * from './version_store.ts';
export * from './tx.ts';
export * from './store.ts';
""",
"test/kv.test.ts": """
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { KVStore } from '../src/index.ts';

describe('mvcc-kv baseline', () => {
  it('sets, gets, and commits basic values', () => {
    const store = new KVStore();
    const tx1 = store.begin();
    tx1.set('a', '1');
    tx1.set('b', '2');
    assert.equal(tx1.get('a'), '1');
    tx1.commit();

    const tx2 = store.begin();
    assert.equal(tx2.get('a'), '1');
    assert.equal(tx2.get('b'), '2');
    assert.equal(tx2.get('c'), undefined);
    tx2.commit();
  });

  it('scans keys in sorted order', () => {
    const store = new KVStore();
    const tx = store.begin();
    tx.set('b', '2');
    tx.set('a', '1');
    tx.set('c', '3');
    tx.commit();

    const r = store.begin();
    assert.deepEqual(r.scan({ start: 'a', end: 'c' }), [
      { key: 'a', value: '1' },
      { key: 'b', value: '2' },
    ]);
    r.commit();
  });
});
"""
}

C5_GRADING = {
"hidden_grading.test.ts": """
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { KVStore, ConflictError } from '../src/index.ts';

describe('C5 MVCC KVStore hidden grading suite', () => {
  it('1. uncommitted writes are invisible to other transactions (no dirty reads) and discarded on rollback', () => {
    const store = new KVStore();
    const tx1 = store.begin();
    tx1.set('k', 'uncommitted');
    assert.equal(tx1.get('k'), 'uncommitted');

    const tx2 = store.begin();
    assert.equal(tx2.get('k'), undefined);
    assert.deepEqual(tx2.scan(), []);

    tx1.rollback();
    assert.equal(tx1.status, 'aborted');

    const tx3 = store.begin();
    assert.equal(tx3.get('k'), undefined);
    tx2.commit();
    tx3.commit();
  });

  it('2. snapshot isolation: open reader sees consistent snapshot across concurrent updates and deletes', () => {
    const store = new KVStore();
    const init = store.begin();
    init.set('a', 'v1');
    init.set('b', 'v1');
    init.commit();

    const reader = store.begin();
    assert.equal(reader.get('a'), 'v1');

    const writer = store.begin();
    writer.set('a', 'v2');
    writer.delete('b');
    writer.set('c', 'new');
    writer.commit();

    // reader must still see exact pre-writer snapshot (no non-repeatable reads, no phantoms)
    assert.equal(reader.get('a'), 'v1');
    assert.equal(reader.get('b'), 'v1');
    assert.equal(reader.get('c'), undefined);
    assert.deepEqual(reader.scan(), [
      { key: 'a', value: 'v1' },
      { key: 'b', value: 'v1' },
    ]);
    reader.commit();

    // new transaction sees post-writer state
    const after = store.begin();
    assert.equal(after.get('a'), 'v2');
    assert.equal(after.get('b'), undefined);
    assert.equal(after.get('c'), 'new');
    assert.deepEqual(after.scan(), [
      { key: 'a', value: 'v2' },
      { key: 'c', value: 'new' },
    ]);
    after.commit();
  });

  it('3. read-your-own-writes including delete-after-set and set-after-delete', () => {
    const store = new KVStore();
    const init = store.begin();
    init.set('k1', 'old1');
    init.set('k2', 'old2');
    init.commit();

    const tx = store.begin();
    tx.delete('k1');
    assert.equal(tx.get('k1'), undefined);
    tx.set('k1', 'revived');
    assert.equal(tx.get('k1'), 'revived');

    tx.set('k3', 'temp');
    assert.equal(tx.get('k3'), 'temp');
    tx.delete('k3');
    assert.equal(tx.get('k3'), undefined);
    tx.commit();

    const check = store.begin();
    assert.equal(check.get('k1'), 'revived');
    assert.equal(check.get('k2'), 'old2');
    assert.equal(check.get('k3'), undefined);
    check.commit();
  });

  it('4. first-committer-wins write-write conflict detection aborts atomically without partial writes', () => {
    const store = new KVStore();
    const init = store.begin();
    init.set('x', '0');
    init.set('y', '0');
    init.commit();

    const tx1 = store.begin();
    const tx2 = store.begin();

    tx1.set('x', 'from_tx1');
    tx2.set('y', 'from_tx2_no_conflict');
    tx2.set('x', 'from_tx2_conflict');
    tx2.set('z', 'from_tx2_extra');

    tx1.commit();

    assert.throws(() => tx2.commit(), (err: unknown) => {
      assert.ok(err instanceof ConflictError, `expected ConflictError, got ${err}`);
      assert.equal(err.key, 'x');
      return true;
    });
    assert.equal(tx2.status, 'aborted');

    // NONE of tx2's writes (y, x, z) may have leaked!
    const verify = store.begin();
    assert.equal(verify.get('x'), 'from_tx1');
    assert.equal(verify.get('y'), '0');
    assert.equal(verify.get('z'), undefined);
    verify.commit();
  });

  it('5. write-write conflict detects concurrent delete vs update and concurrent insert of same new key', () => {
    const store = new KVStore();
    const init = store.begin();
    init.set('item', 'alive');
    init.commit();

    // Concurrent delete vs update
    const tDel = store.begin();
    const tUpd = store.begin();
    tDel.delete('item');
    tUpd.set('item', 'updated');
    tDel.commit();
    assert.throws(() => tUpd.commit(), ConflictError);

    // Concurrent insert of brand-new key
    const tIns1 = store.begin();
    const tIns2 = store.begin();
    tIns1.set('brand_new', '1');
    tIns2.set('brand_new', '2');
    tIns1.commit();
    assert.throws(() => tIns2.commit(), ConflictError);

    const check = store.begin();
    assert.equal(check.get('item'), undefined);
    assert.equal(check.get('brand_new'), '1');
    check.commit();
  });

  it('6. disjoint concurrent writers commit cleanly without false conflicts', () => {
    const store = new KVStore();
    const t1 = store.begin();
    const t2 = store.begin();
    t1.set('k1', 'v1');
    t2.set('k2', 'v2');
    const ts1 = t1.commit();
    const ts2 = t2.commit();
    assert.ok(ts2 > ts1);

    const r = store.begin();
    assert.equal(r.get('k1'), 'v1');
    assert.equal(r.get('k2'), 'v2');
    r.commit();
  });

  it('7. read-only transaction never conflicts even if keys it read were modified concurrently', () => {
    const store = new KVStore();
    const init = store.begin();
    init.set('a', '1');
    init.commit();

    const ro = store.begin();
    assert.equal(ro.get('a'), '1');

    const w = store.begin();
    w.set('a', '2');
    w.commit();

    // Snapshot isolation allows read-only tx to commit cleanly
    ro.commit();
    assert.equal(ro.status, 'committed');
  });

  it('8. nested savepoints: rollbackTo reverts writes/deletes accurately and keeps target savepoint active', () => {
    const store = new KVStore();
    const init = store.begin();
    init.set('a', 'base_a');
    init.set('b', 'base_b');
    init.commit();

    const tx = store.begin();
    tx.set('a', 'tx_a1');
    tx.savepoint('sp1');
    tx.set('a', 'tx_a2');
    tx.delete('b');
    tx.set('c', 'tx_c');
    tx.savepoint('sp2');
    tx.set('d', 'tx_d');
    tx.set('a', 'tx_a3');

    // Roll back to sp1: discards sp2, reverts a->tx_a1, b->base_b, c->undefined, d->undefined
    tx.rollbackTo('sp1');
    assert.equal(tx.get('a'), 'tx_a1');
    assert.equal(tx.get('b'), 'base_b');
    assert.equal(tx.get('c'), undefined);
    assert.equal(tx.get('d'), undefined);

    // sp2 was discarded by rolling back to sp1
    assert.throws(() => tx.rollbackTo('sp2'));

    // sp1 itself remains active and can be rolled back to again!
    tx.set('e', 'temp_e');
    tx.rollbackTo('sp1');
    assert.equal(tx.get('e'), undefined);

    tx.commit();
    const r = store.begin();
    assert.deepEqual(r.scan(), [
      { key: 'a', value: 'tx_a1' },
      { key: 'b', value: 'base_b' },
    ]);
    r.commit();
  });

  it('9. rolling back a savepoint removes rolled-back keys from commit write-set (no phantom conflict!)', () => {
    const store = new KVStore();
    const init = store.begin();
    init.set('hot', '0');
    init.set('mine', '0');
    init.commit();

    const tx1 = store.begin();
    tx1.set('mine', '1');
    tx1.savepoint('s1');
    tx1.set('hot', 'tentative');
    tx1.rollbackTo('s1'); // tx1 NO LONGER writes 'hot'

    const tx2 = store.begin();
    tx2.set('hot', 'winner');
    tx2.commit();

    // tx1 MUST commit cleanly since its write to 'hot' was rolled back!
    tx1.commit();

    const r = store.begin();
    assert.equal(r.get('hot'), 'winner');
    assert.equal(r.get('mine'), '1');
    r.commit();
  });

  it('10. releaseSavepoint merges changes into parent and removes target + inner savepoints', () => {
    const store = new KVStore();
    const tx = store.begin();
    tx.savepoint('outer');
    tx.set('k1', 'v1');
    tx.savepoint('inner');
    tx.set('k2', 'v2');

    tx.releaseSavepoint('outer');
    // Both outer and inner are gone, changes persist in tx
    assert.throws(() => tx.rollbackTo('inner'));
    assert.throws(() => tx.rollbackTo('outer'));
    assert.equal(tx.get('k1'), 'v1');
    assert.equal(tx.get('k2'), 'v2');
    tx.commit();

    const r = store.begin();
    assert.equal(r.get('k1'), 'v1');
    assert.equal(r.get('k2'), 'v2');
    r.commit();
  });

  it('11. duplicate savepoint name shadows earlier savepoint and rolls back to most recent', () => {
    const store = new KVStore();
    const tx = store.begin();
    tx.set('x', '0');
    tx.savepoint('s');
    tx.set('x', '1');
    tx.savepoint('s');
    tx.set('x', '2');

    tx.rollbackTo('s');
    assert.equal(tx.get('x'), '1');

    tx.releaseSavepoint('s');
    tx.set('x', '3');
    tx.rollbackTo('s'); // outer 's' is still there!
    assert.equal(tx.get('x'), '0');
    tx.commit();
  });

  it('12. scan merges snapshot + uncommitted inserts/updates/deletes, applies prefix/start/end, and applies limit AFTER tombstones', () => {
    const store = new KVStore();
    const init = store.begin();
    init.set('u:1', 'a');
    init.set('u:2', 'b');
    init.set('u:3', 'c');
    init.set('u:4', 'd');
    init.set('z:1', 'z');
    init.commit();

    const tx = store.begin();
    tx.delete('u:1');        // hides snapshot key
    tx.set('u:2', 'b_new');  // overrides snapshot key
    tx.set('u:25', 'mid');   // new key sorted between u:2 and u:3

    // limit: 2 MUST return u:2 and u:25 (not stop early because u:1 was tombstoned!)
    assert.deepEqual(tx.scan({ prefix: 'u:', limit: 2 }), [
      { key: 'u:2', value: 'b_new' },
      { key: 'u:25', value: 'mid' },
    ]);

    assert.deepEqual(tx.scan({ start: 'u:2', end: 'u:4' }), [
      { key: 'u:2', value: 'b_new' },
      { key: 'u:25', value: 'mid' },
      { key: 'u:3', value: 'c' },
    ]);

    // limit: 0 returns []
    assert.deepEqual(tx.scan({ limit: 0 }), []);
    tx.rollback();
  });

  it('13. compact() preserves versions visible to active snapshots and collects unreachable historical versions + tombstones', () => {
    const store = new KVStore();

    // Write 5 versions of 'k' and 1 key 'temp' that gets deleted
    for (let i = 1; i <= 3; i++) {
      const t = store.begin();
      t.set('k', `v${i}`);
      if (i === 1) t.set('temp', 'here');
      t.commit();
    }

    // Open a long-running reader at v3
    const snapV3 = store.begin();
    assert.equal(snapV3.get('k'), 'v3');
    assert.equal(snapV3.get('temp'), 'here');

    // Write v4, v5, and delete 'temp'
    for (let i = 4; i <= 5; i++) {
      const t = store.begin();
      t.set('k', `v${i}`);
      if (i === 4) t.delete('temp');
      t.commit();
    }

    const beforeCompact = store.stats().totalVersions;
    assert.ok(beforeCompact >= 7, `Expected >=7 versions before compact, got ${beforeCompact}`);

    // Compact while snapV3 is active: v1 and v2 are unreachable (snapV3 sees v3),
    // v4 is unreachable (no active tx at v4; latest is v5),
    // BUT v3, v5, temp@v1, and temp tombstone@v4 MUST remain visible!
    const c1 = store.compact();
    assert.ok(c1.removedVersions >= 2, `Expected compact to remove >=2 old versions, removed ${c1.removedVersions}`);

    // snapV3 MUST still see v3 and temp='here'!
    assert.equal(snapV3.get('k'), 'v3');
    assert.equal(snapV3.get('temp'), 'here');

    // Latest reader MUST see v5 and temp=undefined!
    const latest1 = store.begin();
    assert.equal(latest1.get('k'), 'v5');
    assert.equal(latest1.get('temp'), undefined);
    latest1.commit();

    // Close snapV3 -> now compact should prune v3 AND completely remove 'temp' (both v1 and tombstone)!
    snapV3.commit();
    const c2 = store.compact();
    assert.ok(c2.removedVersions >= 2, `Expected second compact to prune v3 and temp versions, removed ${c2.removedVersions}`);

    const afterStats = store.stats();
    assert.equal(afterStats.activeTransactions, 0);
    assert.equal(afterStats.totalKeys, 1, `Expected only 'k' remaining after tombstone GC, got ${afterStats.totalKeys}`);
    assert.equal(afterStats.totalVersions, 1, `Expected only 1 version (v5) remaining, got ${afterStats.totalVersions}`);

    const finalRead = store.begin();
    assert.equal(finalRead.get('k'), 'v5');
    assert.equal(finalRead.get('temp'), undefined);
    finalRead.commit();
  });

  it('14. operations on committed or aborted transactions throw', () => {
    const store = new KVStore();
    const tx = store.begin();
    tx.set('a', '1');
    tx.commit();
    assert.throws(() => tx.get('a'));
    assert.throws(() => tx.set('a', '2'));
    assert.throws(() => tx.delete('a'));
    assert.throws(() => tx.scan());
    assert.throws(() => tx.commit());
    assert.throws(() => tx.savepoint('s'));

    const tx2 = store.begin();
    tx2.rollback();
    assert.throws(() => tx2.get('a'));
    assert.throws(() => tx2.set('a', '2'));
    assert.throws(() => tx2.commit());
  });
});
"""
}

def main():
    parser = argparse.ArgumentParser(description="Build C5 fixer-bench template and grading suite")
    parser.add_argument("--work-dir", default="/tmp/opencode/fixer-bench", help="Benchmark work directory")
    args = parser.parse_args()
    base = pathlib.Path(args.work_dir)

    write_files(base / "templates" / "c5-mvcc-kv-ts", C5_FILES)
    git_init(base / "templates" / "c5-mvcc-kv-ts")
    write_files(base / "grading" / "c5-mvcc-kv-ts", C5_GRADING)

    print("Built C5 successfully.")


if __name__ == "__main__":
    main()
