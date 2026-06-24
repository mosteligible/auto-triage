storage "file" {
  path = "/openbao/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1
}

audit "file" "file" {
  description = "Auto-triage OpenBao audit log"

  options {
    file_path = "/openbao/audit/audit.log"
  }
}

api_addr      = "http://openbao:8200"
cluster_addr  = "http://openbao:8201"
ui            = false
