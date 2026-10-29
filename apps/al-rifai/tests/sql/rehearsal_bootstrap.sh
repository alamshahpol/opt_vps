#!/bin/sh
# Create and destroy our own isolated, empty PostgreSQL container. Never accept
# an existing container or database as a target: this rehearsal applies schema.
set -eu

if [ "$#" -ne 0 ]; then
  echo 'Usage: sh tests/sql/rehearsal_bootstrap.sh (no container arguments permitted)' >&2
  exit 64
fi
if ! command -v docker >/dev/null 2>&1; then
  echo 'Docker is required for this disposable rehearsal.' >&2
  exit 69
fi

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
container_id=''
cleanup() {
  if [ -n "$container_id" ]; then
    docker rm -f "$container_id" >/dev/null 2>&1 || :
  fi
}
trap cleanup 0
trap 'exit 1' HUP INT TERM

# No host mounts, published ports or network. Authentication is trust only
# inside this throwaway networkless container; its database lives on tmpfs.
# Pulling images and deploying to a host are outside this script's scope.
created=$(docker run --detach --rm --pull=never --network none \
  --tmpfs /var/lib/postgresql/data:rw,exec,nosuid,size=512m,mode=0700 \
  --memory=768m --pids-limit=128 \
  --label alrifai.test.scope=disposable-migration-rehearsal \
  -e POSTGRES_USER=postgres -e POSTGRES_DB=alrifai \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16-alpine)
# Only a full Docker-generated ID may be used for exec or cleanup.
if ! printf '%s\n' "$created" | grep -Eq '^[0-9a-f]{64}$'; then
  echo 'Docker did not return a valid owned container ID; refusing to continue.' >&2
  exit 1
fi
container_id=$created

attempt=0
until docker exec "$container_id" psql -U postgres -d alrifai -v ON_ERROR_STOP=1 -qtAc 'SELECT 1' >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    echo 'Disposable PostgreSQL did not become ready.' >&2
    exit 1
  fi
  sleep 1
done

docker exec "$container_id" psql -U postgres -d alrifai -v ON_ERROR_STOP=1 -q \
  -c 'CREATE ROLE alrifai_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
apply_migration() {
  file=$1
  if [ ! -f "$file" ]; then
    echo "Missing rehearsal migration: $file" >&2
    exit 1
  fi
  docker exec -i "$container_id" psql -U postgres -d alrifai -v ON_ERROR_STOP=1 -q -f - < "$file" || {
    echo "FAILED: $file" >&2
    exit 1
  }
}
# Exactly the approved baseline, not a wildcard that could silently include a
# newly added migration. Missing or duplicate numbered migrations fail closed.
number=0
while [ "$number" -le 30 ]; do
  prefix=$(printf '%04d' "$number")
  set -- "db/migrations/${prefix}_"*.sql
  if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
    echo "Expected exactly one baseline migration for $prefix." >&2
    exit 1
  fi
  apply_migration "$1"
  number=$((number + 1))
done
for file in db/migration-candidates/0031_cash_submissions_and_reviews.sql \
  db/migration-candidates/0032_vessel_program_commands.sql; do
  apply_migration "$file"
done
for file in tests/sql/0031_cash_review_rehearsal.sql tests/sql/0032_vessel_commands_rehearsal.sql; do
  docker exec -i "$container_id" psql -U postgres -d alrifai -v ON_ERROR_STOP=1 -q -f - < "$file" >/dev/null || {
    echo "FAILED: $file" >&2
    exit 1
  }
done
echo 'REHEARSAL_OK: disposable schema and assertions only; container and data will be removed.'
