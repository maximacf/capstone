# Database Migrations

DB-first system skeleton with explicit SQL migrations.

## Migration Files

- `000_schema_version.sql` - Migration tracking table (created first)
- `001_initial_schema.sql` - Initial schema (bronze/silver/gold tables)
- `002_add_message_fields.sql` - Cross-cutting fields (urgency, FTS, etc.)
- `003_add_mailbox_support.sql` - Mailbox awareness (shared vs personal)

## Idempotency Guarantees

All migrations are **idempotent** - safe to run multiple times:

1. **Schema objects**: Use `IF NOT EXISTS` for tables, indexes, views, triggers
2. **ALTER TABLE**: Python migration runner checks column existence before adding
3. **Data operations**: All upserts use `ON CONFLICT` clauses:
   - `raw_message`: `ON CONFLICT(id) DO UPDATE`
   - `message`: `ON CONFLICT(id) DO UPDATE`
   - `mailbox_emails`: `ON CONFLICT(mailbox_id, canonical_key) DO UPDATE`
   - `attachment`: `ON CONFLICT(id) DO UPDATE`

## Unique Constraints (DB-level idempotency)

- `raw_message.id` (PRIMARY KEY) - Graph message ID
- `raw_message.internet_id` (UNIQUE) - RFC 5322 Message-ID
- `message.id` (PRIMARY KEY) - Graph message ID
- `message.internet_id` (UNIQUE) - RFC 5322 Message-ID
- `mailbox_emails(mailbox_id, canonical_key)` (UNIQUE) - One canonical email per mailbox
- `attachment.id` (PRIMARY KEY) - Graph attachment ID

## Running Migrations

Migrations run automatically when `store_db.connect()` is called. The migration system:
1. Checks `schema_version` table for applied migrations
2. Runs unapplied migrations in order (000, 001, 002, 003...)
3. Records each migration in `schema_version` after successful application

No manual migration commands needed - the DB is always up-to-date on connection.
