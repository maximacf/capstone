# Reset PostgreSQL Password (EnterpriseDB PostgreSQL 16)

Your system is using **PostgreSQL 16** from the EnterpriseDB installer (not Homebrew).
It's running on port 5432 and requires a password.

## Reset the `postgres` user password

1. **Open Terminal** and run:
   ```bash
   sudo -u postgres /Library/PostgreSQL/16/bin/psql -d postgres -c "ALTER USER postgres PASSWORD 'your_new_password';"
   ```

2. If that fails (e.g. "postgres user doesn't exist"), try:
   ```bash
   sudo /Library/PostgreSQL/16/bin/psql -U postgres -d postgres -c "ALTER USER postgres PASSWORD 'your_new_password';"
   ```

3. Replace `your_new_password` with a password you'll remember.

4. Create the database:
   ```bash
   /Library/PostgreSQL/16/bin/createdb -U postgres maildb
   ```
   (It will prompt for the new password.)

5. Set your app's env:
   ```bash
   export DATABASE_URL="postgresql://postgres:your_new_password@localhost:5432/maildb"
   ```

---

## Option B: Use Homebrew PostgreSQL instead (no password)

Stop EnterpriseDB and use Homebrew's PostgreSQL (trust auth, no password):

```bash
# Stop EnterpriseDB PostgreSQL 16 (run from Finder or as admin)
# Or: sudo launchctl unload /Library/LaunchDaemons/com.edb.launchd.postgresql-16.plist

# Start Homebrew PostgreSQL 14
brew services start postgresql@14

# Create database (no password with trust auth)
/usr/local/opt/postgresql@14/bin/createdb -U ifc maildb

# Use port 5433 if 16 is still running (Homebrew 14 often uses 5433)
export DATABASE_URL="postgresql://ifc@localhost:5433/maildb"
```

Check which port Homebrew 14 uses:
```bash
grep port /usr/local/var/postgresql@14/postgresql.conf
```
