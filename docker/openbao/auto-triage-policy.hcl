path "transit/encrypt/auto-triage" {
  capabilities = ["update"]
}

path "transit/decrypt/auto-triage" {
  capabilities = ["update"]
}

path "transit/rewrap/auto-triage" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}
