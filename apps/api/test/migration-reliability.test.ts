import Database from "better-sqlite3";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { z } from "zod";

const MIGRATIONS = [
  "0000_adorable_the_anarchist",
  "0001_flashy_prima",
  "0002_low_giant_girl",
  "0003_rename_owner_id",
  "0004_add_profile_fields",
  "0005_highlight_styles_offsets",
  "0006_drop_highlights_style",
  "0007_silky_ultron",
  "0008_windy_colonel_america",
  "0009_overjoyed_marvel_apes",
  "0010_pink_the_executioner",
  "0011_chubby_medusa",
  "0012_atomic_persistence_foundation",
  "0013_owner_namespace_and_subscription_nonce",
  "0014_resend_newsletter_delivery",
  "0015_abandoned_thunderball",
  "0016_majestic_layla_miller",
  "0017_vengeful_shatterstar",
  "0018_term_favorites",
  "0019_kind_wolverine",
] as const;

const snapshotSchema = z.object({
  id: z.string().uuid(),
  prevId: z.string().uuid(),
  tables: z.object({
    favorites: z.object({ columns: z.record(z.unknown()) }),
    highlights: z.object({ columns: z.record(z.unknown()) }),
    practice: z.object({
      columns: z.record(z.unknown()),
      compositePrimaryKeys: z.record(z.object({ columns: z.array(z.string()), name: z.string() })),
    }),
    users: z.object({ columns: z.record(z.unknown()) }),
  }),
});

function applyRange(sqlite: Database.Database, start: number, end: number = MIGRATIONS.length): void {
  for (const migration of MIGRATIONS.slice(start, end)) {
    const path = fileURLToPath(new URL(`../drizzle/${migration}.sql`, import.meta.url));
    const statements = readFileSync(path, "utf8").split("--> statement-breakpoint");
    for (const statement of statements) {
      if (statement.trim()) sqlite.exec(statement);
    }
  }
}

function readSnapshot(index: string): z.infer<typeof snapshotSchema> {
  const path = fileURLToPath(new URL(`../drizzle/meta/${index}_snapshot.json`, import.meta.url));
  return snapshotSchema.parse(JSON.parse(readFileSync(path, "utf8")));
}

function readSnapshotLineage(index: string): { id: string; prevId: string } {
  const path = fileURLToPath(new URL(`../drizzle/meta/${index}_snapshot.json`, import.meta.url));
  return z.object({ id: z.string().uuid(), prevId: z.string().uuid() }).parse(JSON.parse(readFileSync(path, "utf8")));
}

function readJournal(): { entries: Array<{ idx: number; tag: string }> } {
  const path = fileURLToPath(new URL("../drizzle/meta/_journal.json", import.meta.url));
  return JSON.parse(readFileSync(path, "utf8")) as { entries: Array<{ idx: number; tag: string }> };
}

describe("migration reliability", () => {
  it("keeps snapshots 0003 through 0005 aligned with their SQL states", () => {
    const snapshot0003 = readSnapshot("0003");
    const snapshot0004 = readSnapshot("0004");
    const snapshot0005 = readSnapshot("0005");

    for (const snapshot of [snapshot0003, snapshot0004, snapshot0005]) {
      expect(Object.keys(snapshot.tables.favorites.columns)).toContain("owner_id");
      expect(Object.keys(snapshot.tables.highlights.columns)).toContain("owner_id");
      expect(Object.keys(snapshot.tables.practice.columns)).toContain("owner_id");
      expect(snapshot.tables.practice.compositePrimaryKeys).toHaveProperty("practice_owner_id_date_pk");
    }
    expect(Object.keys(snapshot0003.tables.users.columns)).not.toContain("email");
    expect(Object.keys(snapshot0004.tables.users.columns)).toEqual(expect.arrayContaining(["email", "name", "avatar", "subscribed"]));
    expect(Object.keys(snapshot0005.tables.highlights.columns)).toEqual(expect.arrayContaining(["style", "styles", "paragraph_index", "start_offset", "end_offset"]));
  });

  it("keeps every snapshot prevId and journal entry in migration order", () => {
    const journal = readJournal();
    expect(journal.entries).toHaveLength(MIGRATIONS.length);
    const zeroId = "00000000-0000-0000-0000-000000000000";
    let previousId = zeroId;
    for (let index = 0; index < MIGRATIONS.length; index += 1) {
      const tag = MIGRATIONS[index];
      const snapshot = readSnapshotLineage(String(index).padStart(4, "0"));
      expect(snapshot.prevId).toBe(previousId);
      expect(journal.entries[index]).toMatchObject({ idx: index, tag });
      previousId = snapshot.id;
    }
  });

  it("applies the full migration chain to a fresh database", () => {
    const sqlite = new Database(":memory:");

    applyRange(sqlite, 0);

    const tables = sqlite.prepare(`
      SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name
    `).pluck().all();
    expect(tables).toContain("highlights");
    expect(tables).toContain("highlight_paragraphs");
    const verificationColumns = sqlite.prepare("SELECT name FROM pragma_table_info('email_verification_codes')").pluck().all();
    expect(verificationColumns).toContain("consume_token");
    const deliveryColumns = sqlite.prepare("SELECT name FROM pragma_table_info('mail_deliveries')").pluck().all();
    expect(deliveryColumns).toEqual(expect.arrayContaining(["lease_token", "lease_expires_at"]));
    const userColumns = sqlite.prepare("SELECT name FROM pragma_table_info('users')").pluck().all();
    expect(userColumns).not.toContain("subscribed");
    const subscriptionColumns = sqlite.prepare("SELECT name FROM pragma_table_info('subscriptions')").pluck().all();
    expect(subscriptionColumns).toContain("unsubscribe_token_nonce");
    expect(subscriptionColumns).toEqual(expect.arrayContaining([
      "suppression_reason", "suppressed_at", "suppression_provider_message_id",
    ]));
    expect(deliveryColumns).toEqual(expect.arrayContaining([
      "provider_message_id", "provider_event", "provider_event_at", "last_reconciled_at", "reconcile_attempts", "next_reconcile_at",
    ]));
    expect(tables).toContain("resend_webhook_events");
    const webhookColumns = sqlite.prepare("SELECT name FROM pragma_table_info('resend_webhook_events')").pluck().all();
    expect(webhookColumns).toContain("suppression_reason");
    const indexes = sqlite.prepare("SELECT name FROM sqlite_master WHERE type = 'index'").pluck().all();
    expect(indexes).toEqual(expect.arrayContaining([
      "verification_ip_created_idx",
      "verification_device_created_idx",
      "users_username_unique",
      "users_verified_email_unique",
      "mail_provider_message_idx",
      "resend_webhook_provider_idx",
    ]));
    expect(sqlite.prepare("SELECT name FROM pragma_index_info('verification_ip_created_idx') ORDER BY seqno").pluck().all()).toEqual(["ip_hash", "created_at"]);
    expect(sqlite.prepare("SELECT name FROM pragma_index_info('verification_device_created_idx') ORDER BY seqno").pluck().all()).toEqual(["device_id", "created_at"]);
    expect(sqlite.prepare("PRAGMA integrity_check").pluck().get()).toBe("ok");
  });

  it("upgrades 0011 data while preserving canonical subscriptions and nullable fencing fields", () => {
    const sqlite = new Database(":memory:");
    applyRange(sqlite, 0, 12);
    const insertUser = sqlite.prepare(`
      INSERT INTO users
        (id, username, password_hash, salt, email, name, avatar, subscribed, created_at)
      VALUES (?, ?, 'hash', 'salt', ?, ?, 'avatar', ?, ?)
    `);
    insertUser.run("legacy-on", "legacy-on", "legacy-on@qq.com", "Legacy On", 1, 100);
    insertUser.run("legacy-off", "legacy-off", "legacy-off@qq.com", "Legacy Off", 0, 200);
    insertUser.run("canonical-off", "canonical-off", "canonical-off@qq.com", "Canonical Off", 1, 300);
    insertUser.run("canonical-on", "canonical-on", "canonical-on@qq.com", "Canonical On", 0, 400);
    sqlite.prepare(`
      INSERT INTO subscriptions
        (user_id, status, subscribed_at, unsubscribed_at, unsubscribe_token_hash, updated_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `).run("canonical-off", "unsubscribed", null, 350, null, 350);
    sqlite.prepare(`
      INSERT INTO subscriptions
        (user_id, status, subscribed_at, unsubscribed_at, unsubscribe_token_hash, updated_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `).run("canonical-on", "subscribed", 450, null, "unsubscribe-hash", 450);
    sqlite.prepare(`
      INSERT INTO email_verification_codes
        (id, email, code_hash, expires_at, attempts, consumed_at, ip_hash, device_id, created_at)
      VALUES ('code-1', 'legacy-on@qq.com', 'code-hash', 1000, 1, NULL, 'ip-hash', 'device-1', 500)
    `).run();
    sqlite.prepare(`
      INSERT INTO mail_deliveries
        (id, issue_id, user_id, recipient, status, attempts, last_error, next_attempt_at, sent_at, created_at)
      VALUES ('delivery-1', 'issue-1', 'legacy-on', 'legacy-on@qq.com', 'pending', 0, '', 0, NULL, 600)
    `).run();

    applyRange(sqlite, 12);

    expect(sqlite.prepare("SELECT * FROM users WHERE id = 'legacy-on'").get()).toEqual({
      id: "legacy-on",
      username: "legacy-on",
      password_hash: "hash",
      salt: "salt",
      email: "legacy-on@qq.com",
      name: "Legacy On",
      avatar: "avatar",
      created_at: 100,
    });
    expect(sqlite.prepare("SELECT COUNT(*) FROM users").pluck().get()).toBe(4);
    expect(sqlite.prepare("SELECT name FROM pragma_table_info('users')").pluck().all()).not.toContain("subscribed");
    expect(sqlite.prepare("SELECT user_id, status, subscribed_at, unsubscribed_at, unsubscribe_token_hash, unsubscribe_token_nonce, updated_at FROM subscriptions ORDER BY user_id").all()).toEqual([
      { user_id: "canonical-off", status: "unsubscribed", subscribed_at: null, unsubscribed_at: 350, unsubscribe_token_hash: null, unsubscribe_token_nonce: null, updated_at: 350 },
      { user_id: "canonical-on", status: "subscribed", subscribed_at: 450, unsubscribed_at: null, unsubscribe_token_hash: "unsubscribe-hash", unsubscribe_token_nonce: null, updated_at: 450 },
      { user_id: "legacy-off", status: "unsubscribed", subscribed_at: null, unsubscribed_at: 200, unsubscribe_token_hash: null, unsubscribe_token_nonce: null, updated_at: 200 },
      { user_id: "legacy-on", status: "subscribed", subscribed_at: 100, unsubscribed_at: null, unsubscribe_token_hash: null, unsubscribe_token_nonce: null, updated_at: 100 },
    ]);
    expect(sqlite.prepare("SELECT consume_token FROM email_verification_codes WHERE id = 'code-1'").get()).toEqual({ consume_token: null });
    expect(sqlite.prepare("SELECT lease_token, lease_expires_at FROM mail_deliveries WHERE id = 'delivery-1'").get()).toEqual({ lease_token: null, lease_expires_at: null });
    const indexes = sqlite.prepare("SELECT name FROM sqlite_master WHERE type = 'index'").pluck().all();
    expect(indexes).toEqual(expect.arrayContaining([
      "verification_ip_created_idx",
      "verification_device_created_idx",
      "users_username_unique",
      "users_verified_email_unique",
    ]));
    expect(sqlite.prepare("SELECT name FROM pragma_index_info('verification_ip_created_idx') ORDER BY seqno").pluck().all()).toEqual(["ip_hash", "created_at"]);
    expect(sqlite.prepare("SELECT name FROM pragma_index_info('verification_device_created_idx') ORDER BY seqno").pluck().all()).toEqual(["device_id", "created_at"]);
    expect(sqlite.prepare("PRAGMA integrity_check").pluck().get()).toBe("ok");
  });

  it("upgrades 0012 owner data with exact user matches classified as users and preserves disjoint device keys", () => {
    const sqlite = new Database(":memory:");
    applyRange(sqlite, 0, 13);
    const sharedUuid = "11111111-1111-4111-8111-111111111111";
    const anonymousUuid = "22222222-2222-4222-8222-222222222222";
    sqlite.prepare(`
      INSERT INTO users (id, username, password_hash, salt, email, name, avatar, created_at)
      VALUES (?, 'uuid-user', 'hash', 'salt', 'uuid-user@qq.com', 'UUID User', 'avatar', 10)
    `).run(sharedUuid);
    sqlite.prepare(`
      INSERT INTO subscriptions
        (user_id, status, subscribed_at, unsubscribed_at, unsubscribe_token_hash, updated_at)
      VALUES (?, 'subscribed', 11, NULL, 'legacy-token-hash', 12)
    `).run(sharedUuid);
    sqlite.prepare(`
      INSERT INTO favorites (id, owner_id, url, title, source, note, created_at) VALUES
        ('favorite-user', ?, '/user', 'User Favorite', 'source-user', 'note-user', 20),
        ('favorite-device', ?, '/device', 'Device Favorite', 'source-device', 'note-device', 21)
    `).run(sharedUuid, anonymousUuid);
    sqlite.prepare(`
      INSERT INTO highlights
        (id, owner_id, article_id, text, note, styles, paragraph_index, start_offset, end_offset, created_at)
      VALUES
        ('highlight-user', ?, 'article-user', 'user text', 'user note', '["green"]', 3, 4, 8, 30),
        ('highlight-device', ?, 'article-device', 'device text', 'device note', '["underline"]', 5, 6, 12, 31)
    `).run(sharedUuid, anonymousUuid);
    sqlite.prepare(`
      INSERT INTO highlight_paragraphs
        (owner_id, article_id, paragraph_index, version, spans, updated_at)
      VALUES
        (?, 'article-user', 3, 7, '[{"id":"user-span"}]', 40),
        (?, 'article-device', 5, 8, '[{"id":"device-span"}]', 41)
    `).run(sharedUuid, anonymousUuid);
    sqlite.prepare(`
      INSERT INTO practice (owner_id, date, correct, total) VALUES
        (?, '2026-08-14', 8, 10),
        (?, '2026-08-15', 9, 12)
    `).run(sharedUuid, anonymousUuid);

    applyRange(sqlite, 13);
    sqlite.prepare(`
      INSERT INTO practice (owner_id, date, correct, total)
      VALUES (?, '2026-08-14', 6, 10)
    `).run(`device:${sharedUuid}`);

    expect(sqlite.prepare("SELECT * FROM favorites ORDER BY id").all()).toEqual([
      { id: "favorite-device", owner_id: `device:${anonymousUuid}`, url: "/device", title: "Device Favorite", source: "source-device", note: "note-device", kind: "article", quote: "", term_text: "", term_explanation: "", article_id: "", created_at: 21 },
      { id: "favorite-user", owner_id: `user:${sharedUuid}`, url: "/user", title: "User Favorite", source: "source-user", note: "note-user", kind: "article", quote: "", term_text: "", term_explanation: "", article_id: "", created_at: 20 },
    ]);
    expect(sqlite.prepare("SELECT * FROM highlights ORDER BY id").all()).toEqual([
      { id: "highlight-device", owner_id: `device:${anonymousUuid}`, article_id: "article-device", text: "device text", note: "device note", styles: '["underline"]', paragraph_index: 5, start_offset: 6, end_offset: 12, created_at: 31 },
      { id: "highlight-user", owner_id: `user:${sharedUuid}`, article_id: "article-user", text: "user text", note: "user note", styles: '["green"]', paragraph_index: 3, start_offset: 4, end_offset: 8, created_at: 30 },
    ]);
    expect(sqlite.prepare("SELECT * FROM highlight_paragraphs ORDER BY article_id").all()).toEqual([
      { owner_id: `device:${anonymousUuid}`, article_id: "article-device", paragraph_index: 5, version: 8, spans: '[{"id":"device-span"}]', updated_at: 41 },
      { owner_id: `user:${sharedUuid}`, article_id: "article-user", paragraph_index: 3, version: 7, spans: '[{"id":"user-span"}]', updated_at: 40 },
    ]);
    expect(sqlite.prepare("SELECT * FROM practice ORDER BY date, owner_id").all()).toEqual([
      { owner_id: `device:${sharedUuid}`, date: "2026-08-14", correct: 6, total: 10 },
      { owner_id: `user:${sharedUuid}`, date: "2026-08-14", correct: 8, total: 10 },
      { owner_id: `device:${anonymousUuid}`, date: "2026-08-15", correct: 9, total: 12 },
    ]);
    expect(sqlite.prepare("SELECT unsubscribe_token_nonce FROM subscriptions WHERE user_id = ?").get(sharedUuid)).toEqual({ unsubscribe_token_nonce: null });
    expect(sqlite.prepare("SELECT name FROM pragma_index_info('highlights_owner_article_paragraph_idx') ORDER BY seqno").pluck().all()).toEqual(["owner_id", "article_id", "paragraph_index"]);
    expect(sqlite.prepare("PRAGMA integrity_check").pluck().get()).toBe("ok");
  });

  it("normalizes legacy QQ emails, clears duplicate losers, and preserves every account and owner record", () => {
    const sqlite = new Database(":memory:");
    applyRange(sqlite, 0, 11);
    const insertUser = sqlite.prepare(`
      INSERT INTO users
        (id, username, password_hash, salt, email, name, avatar, subscribed, created_at)
      VALUES (?, ?, 'hash', 'salt', ?, ?, 'avatar', 0, ?)
    `);
    insertUser.run("winner", "winner-name", " 123456@QQ.COM ", "Winner", 100);
    insertUser.run("exact-loser", "exact-loser-name", "123456@qq.com", "Exact Loser", 200);
    insertUser.run("variant-loser", "variant-loser-name", "  123456@qq.COM  ", "Variant Loser", 300);
    insertUser.run("invalid", "invalid-name", "legacy@example.com", "Invalid", 400);
    sqlite.prepare(`
      INSERT INTO favorites (id, owner_id, url, title, source, note, created_at)
      VALUES ('loser-favorite', 'exact-loser', '/kept', 'Kept', 'source', 'note', 500)
    `).run();
    sqlite.prepare(`
      INSERT INTO highlights
        (id, owner_id, article_id, text, note, styles, paragraph_index, start_offset, end_offset, created_at)
      VALUES ('loser-highlight', 'variant-loser', 'article', 'text', 'note', '["green"]', 2, 3, 7, 600)
    `).run();
    sqlite.prepare(`
      INSERT INTO practice (owner_id, date, correct, total)
      VALUES ('invalid', '2026-08-15', 8, 10)
    `).run();

    applyRange(sqlite, 11);

    expect(sqlite.prepare("SELECT id, username, email, name FROM users ORDER BY created_at").all()).toEqual([
      { id: "winner", username: "winner-name", email: "123456@qq.com", name: "Winner" },
      { id: "exact-loser", username: "exact-loser-name", email: "", name: "Exact Loser" },
      { id: "variant-loser", username: "variant-loser-name", email: "", name: "Variant Loser" },
      { id: "invalid", username: "invalid-name", email: "", name: "Invalid" },
    ]);
    expect(sqlite.prepare("SELECT COUNT(*) FROM users").pluck().get()).toBe(4);
    expect(sqlite.prepare("SELECT owner_id, title FROM favorites WHERE id = 'loser-favorite'").get()).toEqual({ owner_id: "user:exact-loser", title: "Kept" });
    expect(sqlite.prepare("SELECT owner_id, styles FROM highlights WHERE id = 'loser-highlight'").get()).toEqual({ owner_id: "user:variant-loser", styles: '["green"]' });
    expect(sqlite.prepare("SELECT owner_id, correct, total FROM practice WHERE date = '2026-08-15'").get()).toEqual({ owner_id: "user:invalid", correct: 8, total: 10 });
    expect(() => sqlite.prepare(`
      INSERT INTO users (id, username, password_hash, salt, email, name, avatar, created_at)
      VALUES ('duplicate-username', 'winner-name', 'hash', 'salt', '', '', '', 700)
    `).run()).toThrow(/UNIQUE constraint failed: users\.username/);
    expect(sqlite.prepare("PRAGMA integrity_check").pluck().get()).toBe("ok");
  });

  it("uses stable id ordering to break equal-created-at normalized email ties", () => {
    const sqlite = new Database(":memory:");
    applyRange(sqlite, 0, 11);
    const insertUser = sqlite.prepare(`
      INSERT INTO users
        (id, username, password_hash, salt, email, name, avatar, subscribed, created_at)
      VALUES (?, ?, 'hash', 'salt', ?, '', '', 0, 100)
    `);
    insertUser.run("z-loser", "z-loser", "654321@qq.com");
    insertUser.run("a-winner", "a-winner", " 654321@QQ.COM ");

    applyRange(sqlite, 11);

    expect(sqlite.prepare("SELECT id, email FROM users ORDER BY id").all()).toEqual([
      { id: "a-winner", email: "654321@qq.com" },
      { id: "z-loser", email: "" },
    ]);
    expect(sqlite.prepare("PRAGMA integrity_check").pluck().get()).toBe("ok");
  });

  it("upgrades a database at 0005 and preserves representative legacy highlight data", () => {
    const sqlite = new Database(":memory:");
    applyRange(sqlite, 0, 6);
    sqlite.prepare(`
      INSERT INTO highlights
        (id, owner_id, article_id, text, note, style, styles, paragraph_index, start_offset, end_offset, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run("legacy-green", "owner-1", "article-1", "旧数据", "旧注释", "green", "[]", 3, 4, 7, 1234);

    applyRange(sqlite, 6);

    expect(sqlite.prepare("SELECT * FROM highlights WHERE id = ?").get("legacy-green")).toMatchObject({
      id: "legacy-green",
      owner_id: "device:owner-1",
      article_id: "article-1",
      text: "旧数据",
      note: "旧注释",
      styles: '["green"]',
      paragraph_index: 3,
      start_offset: 4,
      end_offset: 7,
      created_at: 1234,
    });
    const columns = sqlite.prepare("SELECT name FROM pragma_table_info('highlights')").pluck().all();
    expect(columns).not.toContain("style");
    expect(sqlite.prepare("PRAGMA integrity_check").pluck().get()).toBe("ok");
  });
});
