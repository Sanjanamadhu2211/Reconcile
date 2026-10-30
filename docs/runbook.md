# Reconcile runbook

## Backups

Run from `backend/` with the PostgreSQL client tools on PATH, or with `PG_BIN_DIR` set to their folder:

```
python scripts/backup_db.py --out backups
```

- Uses `DATABASE_DIRECT_URL` when it is set (a non-pooled connection), otherwise `DATABASE_URL`.
- The password is passed to `pg_dump` through `PGPASSWORD`. It is never printed or put on the command line.
- The dump is custom format and gets a timestamp in its name. The script refuses to overwrite an existing file and removes a partial file if `pg_dump` fails.

Neon keeps its own history and branches. Treat that as the second line of defence, not the only one. Neon history covers the recent past; the dump is a copy you hold yourself.

Suggested schedule: run `backup_db.py` daily from a machine you control, for example with cron or Task Scheduler, and keep the newest 30 dumps. Copy them off the machine you run it on. Nothing in the repo schedules this for you.

## Restore and verify

Restore only into an empty database.

```
python scripts/restore_db.py --dump backups/reconcile-20260101T000000Z.dump --target-url <URL>
```

- The script refuses a target that already has tables. `--force` restores over them and drops and recreates the objects in the dump. Use it only when you mean to replace the target.
- The dump grants privileges to the `reconcile_app` role. The target cluster must have that role before the restore. Create it as a superuser or with `CREATEROLE`, using the same statement as migration `0004`.
- The script prints the row count for every table after the restore. Compare those counts with the source before you point the application at the restored database.
- Check that `audit_events` still rejects changes: an `UPDATE` on it must fail with "audit_events is append-only".

## Rollback

- Rolling back the application does not roll back migrations. The old code keeps running against the new schema.
- Downgrade a migration only when it is reversible and nothing has written to the new schema since the upgrade.
- Otherwise restore the most recent dump taken before the upgrade, into an empty database, and point the application at it.

## Stopping a runaway import

- Find the batch in the import list. A batch stuck in `processing` is resumed automatically once it has been idle for five minutes; a second worker can then claim it.
- To stop an import early, do not delete rows by hand. `audit_events` is append-only and the import rows are tied to the batch. Let the batch finish or fail, then upload a corrected file.
- Keep the batch id from the log so the audit trail can be read later.

## Benchmark

Run the **Database benchmark** workflow manually from GitHub Actions. It runs the 10,000- and 100,000-order profiles against a temporary PostgreSQL database, then prints the JSON reports in the job log. The temporary database is discarded with the job. The benchmark leaves its organization, user, and append-only audit events in the database it uses, so do not point it at a shared or production database.

Record the runner, Python and PostgreSQL versions with the measured import and reconciliation throughput and match accuracy. Results are specific to the runner and should not be treated as a production capacity guarantee.

## Incident checklist

1. Check the Render logs (API) and the Vercel logs (frontend) for the time window.
2. Find the request id in the failing response or log line, and search the logs for it.
3. Look at the `reconcile.metrics` events for the same window: import and reconciliation durations, counts, and failures.
4. If the problem is in data, read the `audit_events` rows for the workspace; they show who did what and when.
5. Record what you found and what you changed before you close the incident.

## Database access

The database login the deployment uses must be a member of the `reconcile_app` role. The application's grants are given to that role, so a login without it cannot read or write the application tables.
