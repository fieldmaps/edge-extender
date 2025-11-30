#!/bin/sh
pg_ctl start -D /var/lib/postgresql/data > /dev/null 2>&1
exec "$@"
