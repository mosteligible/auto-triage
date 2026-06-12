set -eu

: "${REDIS_USERNAME:=auto_triage}"
: "${REDIS_PASSWORD:?REDIS_PASSWORD is required}"

case "$REDIS_USERNAME" in
    ""|*[!a-zA-Z0-9_-]*)
        echo "REDIS_USERNAME may only contain letters, numbers, underscore, and dash" >&2
        exit 1
        ;;
esac

password_hash="$(printf '%s' "$REDIS_PASSWORD" | sha256sum | awk '{print $1}')"
acl_file="/tmp/redis-users.acl"

{
    printf 'user default off\n'
    printf 'user %s on #%s ~* &* +@all\n' "$REDIS_USERNAME" "$password_hash"
} > "$acl_file"

exec redis-server --appendonly yes --aclfile "$acl_file"
