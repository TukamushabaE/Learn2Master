# Supabase production setup

Learn2Master uses Supabase as a private object-storage layer for teacher study-material originals. Processed, bounded summaries and upload metadata remain in the application database so the AI knowledge base can be restored after a Render restart.

## 1. Create the private bucket

1. In the Supabase dashboard, open **Storage** and create a bucket named `knowledge-base`.
2. Keep the bucket **private**.
3. Set the bucket file-size limit to at least 100 MB and allow the document MIME types used by the school.
4. Do not add a public read policy. Learn2Master accesses the bucket only from its server.

The application stores objects below `teachers/<teacher-id>/`. It does not expose a public object URL.

## 2. Add Render environment variables

In the Render service, add:

```text
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=<backend secret key>
SUPABASE_STORAGE_BUCKET=knowledge-base
SUPABASE_VECTOR_ENABLED=0
```

Use a Supabase secret key (or the legacy service-role key if the project has not migrated to the new key format). The key bypasses Storage policies and must remain server-side. Never put it in a browser script, template, source-control commit, screenshot, or `SUPABASE_ANON_KEY` field.

After redeployment, the teacher upload page should show **Supabase Storage connected**. A successful upload records **Private original stored in Supabase**.

## 3. Database choice and safe migration

Supabase Storage can be enabled without replacing the current Render PostgreSQL database. This is the safest first deployment because current accounts and research records remain untouched.

If the application database will also move to Supabase PostgreSQL:

1. Back up the current Render PostgreSQL database with `pg_dump`.
2. Restore that dump into Supabase PostgreSQL and verify row counts before changing production.
3. In Supabase, copy the **Shared Pooler / Supavisor session-mode** connection string. Render needs an IPv4-compatible connection; the direct Supabase database hostname may resolve only over IPv6.
4. Set Render `DATABASE_URL` to the session-pooler connection string and redeploy.
5. Verify logins, teacher assignments, learning outcomes and research participant records before removing the old database.

Do not point `DATABASE_URL` at an empty Supabase database. That would make existing production data appear to be lost. The application applies its additive schema columns automatically at startup, but it does not copy data between providers.

## 4. Optional vector search

Leave `SUPABASE_VECTOR_ENABLED=0` unless the Supabase database has the `kb_documents` table, an embedding column, suitable row security, and a compatible `match_kb_chunks` function. The default configuration uses persisted summaries with local semantic or lexical retrieval and does not require those database objects.

## Operational checks

- Upload a small `.txt` or `.docx` file from a teacher account.
- Confirm the UI reports private Supabase storage.
- Confirm the object appears in the private bucket below the correct teacher folder.
- Restart the Render service and confirm the processed knowledge-base entry still appears.
- Rotate the Supabase secret immediately if it is ever exposed.
