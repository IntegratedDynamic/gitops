{{/*
sso-lib.protect — gates one app's own HTTPRoute behind GitHub org SSO via
Dex (see platform/scaleway/dex.yml). Renders a SecurityPolicy (native OIDC —
Envoy Gateway requires redirectURL to live on the target HTTPRoute's own
hostname, so this is one resource per protected app, not a shared policy)
plus the ReferenceGrant letting it reach Dex's Service across namespaces.

Usage, from the consuming app's own template (e.g. apps/demo/templates/securitypolicy.yaml):

  {{- if .Values.auth.enabled }}
  {{ include "sso-lib.protect" (dict "root" $ "auth" .Values.auth) }}
  {{- end }}

Requires in the consuming chart's Chart.yaml:

  dependencies:
    - name: sso-lib
      version: 0.1.0
      repository: "file://../_sso-lib"

...and a `helm dependency update <chart>` run afterwards (vendors a copy
into <chart>/charts/ — re-run it whenever this library's template changes,
consuming charts don't pick up edits automatically).

.auth must provide: issuer, clientID, clientSecretName, cookieDomain,
hostname, dexServiceName, dexServiceNamespace, dexServicePort.
*/}}
{{- define "sso-lib.protect" -}}
{{- $root := .root -}}
{{- $auth := .auth -}}
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata:
  name: {{ $root.Release.Name }}-sso
  namespace: {{ $root.Release.Namespace }}
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      name: {{ $root.Release.Name }}
  oidc:
    provider:
      issuer: {{ $auth.issuer | quote }}
      # Talks to Dex's in-cluster Service directly rather than resolving the
      # issuer hostname — avoids depending on external-dns/Scaleway DNS
      # propagation (this caused a real outage on cluster restart: the
      # Gateway LB IP changes, and envoy-gateway retried OIDC discovery
      # before the new record propagated, wedging the policy Invalid).
      backendRefs:
        - name: {{ $auth.dexServiceName }}
          namespace: {{ $auth.dexServiceNamespace }}
          port: {{ $auth.dexServicePort }}
      # Spelled out explicitly (Dex's standard OIDC paths) so the
      # controller's admission-time validation skips its own discovery
      # fetch entirely — that fetch ignores backendRefs and used plain DNS.
      authorizationEndpoint: "{{ $auth.issuer }}/auth"
      tokenEndpoint: "{{ $auth.issuer }}/token"
    clientID: {{ $auth.clientID | quote }}
    clientSecret:
      name: {{ $auth.clientSecretName }}
    redirectURL: "https://{{ $auth.hostname }}/oauth2/callback"
    logoutPath: "/oauth2/logout"
    cookieDomain: {{ $auth.cookieDomain | quote }}
---
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: {{ $root.Release.Name }}-sso-to-dex
  namespace: {{ $auth.dexServiceNamespace }}
spec:
  from:
    - group: gateway.envoyproxy.io
      kind: SecurityPolicy
      namespace: {{ $root.Release.Namespace }}
  to:
    - group: ""
      kind: Service
      name: {{ $auth.dexServiceName }}
{{- end -}}
