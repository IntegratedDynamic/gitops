{{/*
The four env vars every Workspace needs: the Scaleway state-bucket
credentials, surfaced under BOTH the literal AWS_* names (the only names
OpenTofu's native `backend "s3"` block reads, Scaleway endpoint included)
AND the SCW_* names (every root's `data.external.scw_credentials` →
`local.scaleway_state_backend` cross-root reads). Same value, two name
pairs, from one ESO-synced Secret in this namespace.
*/}}
{{- define "crossplane-config.stateCredentialsEnv" -}}
- name: AWS_ACCESS_KEY_ID
  secretKeyRef:
    namespace: {{ .Values.namespace }}
    name: {{ .Values.stateCredentials.secretName }}
    key: SCW_ACCESS_KEY
- name: AWS_SECRET_ACCESS_KEY
  secretKeyRef:
    namespace: {{ .Values.namespace }}
    name: {{ .Values.stateCredentials.secretName }}
    key: SCW_SECRET_KEY
- name: SCW_ACCESS_KEY
  secretKeyRef:
    namespace: {{ .Values.namespace }}
    name: {{ .Values.stateCredentials.secretName }}
    key: SCW_ACCESS_KEY
- name: SCW_SECRET_KEY
  secretKeyRef:
    namespace: {{ .Values.namespace }}
    name: {{ .Values.stateCredentials.secretName }}
    key: SCW_SECRET_KEY
{{- end -}}
