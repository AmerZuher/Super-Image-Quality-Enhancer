#!/bin/sh
# Creates Temporal's two databases and applies its schema. Safe to run on every start:
# existing databases are kept and update-schema only applies missing versions.
set -eu

tool() {
  temporal-sql-tool --plugin postgres12 --ep "${POSTGRES_SEEDS}" -p "${DB_PORT}" \
    -u "${POSTGRES_USER}" --pw "${POSTGRES_PWD}" --db "$1" "$2" "$3" "$4"
}

for db in temporal temporal_visibility; do
  temporal-sql-tool --plugin postgres12 --ep "${POSTGRES_SEEDS}" -p "${DB_PORT}" \
    -u "${POSTGRES_USER}" --pw "${POSTGRES_PWD}" --db "$db" create-database 2>/dev/null \
    && echo "created database $db" || echo "database $db already exists"
done

SCHEMA=/etc/temporal/schema/postgresql/v12
tool temporal setup-schema -v 0.0 2>/dev/null || true
tool temporal update-schema -d "$SCHEMA/temporal/versioned"
tool temporal_visibility setup-schema -v 0.0 2>/dev/null || true
tool temporal_visibility update-schema -d "$SCHEMA/visibility/versioned"
echo "temporal schema is up to date"
