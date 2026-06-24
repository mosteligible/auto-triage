#!/bin/sh
set -eu

export BAO_ADDR="${BAO_ADDR:-http://127.0.0.1:8200}"
bootstrap_dir=/openbao/bootstrap
credentials_dir=/openbao/app-credentials
audit_dir=/openbao/audit
root_token_file="${bootstrap_dir}/root-token"
unseal_key_file="${bootstrap_dir}/unseal-key"

mkdir -p "${bootstrap_dir}" "${credentials_dir}" "${audit_dir}"
chmod 700 "${bootstrap_dir}" "${credentials_dir}" "${audit_dir}"

bao server -config=/openbao/config/openbao.hcl &
server_pid=$!

cleanup() {
  kill "${server_pid}" 2>/dev/null || true
  wait "${server_pid}" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

until bao status >/tmp/openbao-status 2>&1; do
  status=$?
  if [ "${status}" -eq 2 ]; then
    break
  fi
  sleep 1
done

if ! bao status 2>&1 | grep -q "Initialized.*true"; then
  init_output="$(bao operator init -key-shares=1 -key-threshold=1)"
  printf '%s\n' "${init_output}" \
    | awk -F': ' '/^Unseal Key 1:/ {print $2}' >"${unseal_key_file}"
  printf '%s\n' "${init_output}" \
    | awk -F': ' '/^Initial Root Token:/ {print $2}' >"${root_token_file}"
  chmod 600 "${unseal_key_file}" "${root_token_file}"
fi

if bao status 2>&1 | grep -q "Sealed.*true"; then
  bao operator unseal "$(cat "${unseal_key_file}")" >/dev/null
fi

export BAO_TOKEN="$(cat "${root_token_file}")"

if ! bao secrets list | grep -q '^transit/'; then
  bao secrets enable transit >/dev/null
fi

if ! bao read "${OPENBAO_TRANSIT_MOUNT:-transit}/keys/${OPENBAO_TRANSIT_KEY:-auto-triage}" \
  >/dev/null 2>&1; then
  bao write \
    "${OPENBAO_TRANSIT_MOUNT:-transit}/keys/${OPENBAO_TRANSIT_KEY:-auto-triage}" \
    derived=true type=aes256-gcm96 >/dev/null
fi

if ! bao auth list | grep -q "^${OPENBAO_AUTH_MOUNT:-approle}/"; then
  bao auth enable -path="${OPENBAO_AUTH_MOUNT:-approle}" approle >/dev/null
fi

bao policy write auto-triage /openbao/config/auto-triage-policy.hcl >/dev/null
bao write \
  "auth/${OPENBAO_AUTH_MOUNT:-approle}/role/auto-triage" \
  token_policies=auto-triage \
  token_ttl=15m \
  token_max_ttl=1h \
  secret_id_ttl=0 >/dev/null

bao read -field=role_id \
  "auth/${OPENBAO_AUTH_MOUNT:-approle}/role/auto-triage/role-id" \
  >"${credentials_dir}/role-id"
bao write -f -field=secret_id \
  "auth/${OPENBAO_AUTH_MOUNT:-approle}/role/auto-triage/secret-id" \
  >"${credentials_dir}/secret-id"
chmod 600 "${credentials_dir}/role-id" "${credentials_dir}/secret-id"
touch "${credentials_dir}/ready"

wait "${server_pid}"
