# `bootstrap` — wave design history

`values.yaml`'s `scalewayApps` list keeps only the load-bearing "why" for
each wave's placement — the reasoning that actually protects against
someone "simplifying" it into a live bug. This file is the fuller
archaeology: abandoned designs, the specific incidents that drove a given
wave assignment, and renaming history. Read it when the short version in
`values.yaml` isn't enough, or before changing a wave assignment that looks
arbitrary but isn't.

**infra#84 (2026-08-24, scope extended 2026-08-25):** OpenBao+ESO (former
waves 0-1), monitoring minus Grafana (former waves 2-3:
kube-prometheus-stack-crds, kube-prometheus-stack, loki, tempo, alloy,
otel-collector), Velero (former wave 4), and cluster networking —
envoy-gateway, cert-manager (+ its Scaleway DNS01 webhook), external-dns,
gateway-config (former waves 4/5/6) — were extracted out of this chart
entirely into the infrastructure repo's own
`10-cluster/scaleway/platform-apps/` chart — four Applications
(`secrets-apps`/`monitoring-apps`/`backups-apps`/`networking-apps`) created
directly by that repo's `argocd.tf`, started in parallel with each other,
and required to reach Healthy before Terraform even creates `bootstrap`'s
own Application resource (see that chart's own README.md for the full
mechanism — plain ArgoCD sync-wave can't express ordering across
independent top-level Applications, only within one parent's own sync,
which is exactly why this extraction needed a Terraform-side gate instead
of just another wave number). Every product-specific `*-gateway`
HTTPRoute-only chart (`dex-gateway`, `grafana-gateway`,
`argocd-config-gateway`, `openbao-gateway`, `argo-workflows-gateway`) stays
right here — per-product exposure, not shared routing infrastructure. The
wave sections below for the extracted apps are kept for their
still-relevant intra-domain reasoning (now applying inside the infra repo's
`platform-apps` chart instead of here) — each is marked with where it
moved. Every wave that's still live in `values.yaml` today is unaffected by
this move; their own prerequisites (OpenBao/ESO, Velero, the shared
Gateway) now finish even earlier (before `bootstrap` starts at all) than
they did as this chart's own waves.

`thanos-secret`/`loki-secret`/`tempo-secret`/`velero/secret` (the
ExternalSecret-only charts wave 1 used to hold for these four) were deleted
outright, not moved — the credentials they materialized are now written
directly as Kubernetes Secrets by the infrastructure repo's
`10-cluster/scaleway/main.tf`, since Terraform already originates all four
(`03-storage/scaleway`'s workload identities) and OpenBao/ESO added a hop
with nothing to gain. OpenBao still gets the same values independently
(`11-secrets/openbao/managed`'s `vault_kv_secret_v2` writes, unchanged) —
see infra repo's `platform-apps/README.md` for the full reasoning.

**infra#84 follow-up (2026-08-25, migration finished):** every app still
listed in `values.yaml` after the note above — `dex`, every `*-secret`
chart (`wireguard-secret`, `dex-secret`, `grafana-secret`,
`argo-workflows-secret`), `argo-workflows`, `argocd-config-monitoring`,
`grafana`, `wireguard-config`, every remaining `*-gateway` chart
(`dex-gateway`, `argocd-config-gateway`, `openbao-gateway`,
`argo-workflows-gateway`, `grafana-gateway`), `argocd-config`, and
`terraform-apply` (since replaced by `crossplane`, infra#101) — moved to
the infra repo's `platform-apps/` chart too.
`demo` is the only app left in this file: everything else in this repo's
`services/platform/` turned out to be platform-level infra, not
product-level, once looked at properly (per the issue's own scope-extension
comment), so there was no principled reason left to leave it here by
default. Also generalized in the same pass: every `*-secret` (ExternalSecret)
chart — including the two (`cert-manager-webhook-secret`/
`external-dns-secret`) already moved by the note above — now lives in ONE
dedicated `eso-data-apps` domain instead of being bundled with its own
consumer, fixing a real bug found live (2026-08-25): `cert-manager-webhook-secret`/
`external-dns-secret` could get their ESO cleanup finalizer stranded on
`terraform destroy` when their old owning domain (`networking-apps`) and
`secrets-apps` (ESO's own domain) tore down in parallel with no ordering
between them. Centralizing every ExternalSecret in one place, with that one
place depending on `secrets-apps`, fixes this for every consumer at once
instead of requiring a per-domain special case — see infra repo's
`platform-apps/README.md` (`helm_release.eso_data_apps`) for the full
mechanism. `services/platform/argocd-config/config` was split into
`services/platform/argocd-config/secret` (the ExternalSecret, now feeding
`eso-data-apps`) + a trimmed `config` (just the PostSync restart-hook) as
part of this — same "mixed chart split in two" treatment wave 1's own
history above already documents for `dex`/`grafana`.

## Why sync-wave on one Application's own resources, not an ApplicationSet

Every scaleway Application is rendered directly as a managed resource of
the `bootstrap` Application's own sync (`bootstrap/templates/scaleway.yaml`)
— confirmed live 2026-08-11: ArgoCD's Progressive Syncs (RollingSync)
strategy does not gate the *first-ever* creation/sync of Applications an
ApplicationSet generates. Every stage's apps got created AND synced
simultaneously on a fresh ApplicationSet, regardless of RollingSync step
order, because each generated Application carries its own independent
`syncPolicy.automated` and the ArgoCD Application controller (a separate
process from the ApplicationSet controller) picks it up immediately.
RollingSync appears to only pace staged *updates* across an already-existing
fleet, not bootstrap ordering of brand-new ones.

Plain sync-wave on resources of ONE parent Application's own sync (what the
list produces) is the actually-proven mechanism — it's what
services-vendor-scaleway used successfully for cert-manager (-1) vs openbao
(0) before this list replaced it.

## Wave 0 — openbao + openbao-init

**Moved to the infra repo's `platform-apps/values-secrets.yaml` wave 0
(infra#84, 2026-08-24)** — this app no longer lives in this repo's
`bootstrap` at all. Reasoning below still applies verbatim, just in that
file now.

These were split into waves 0/1 for most of this file's history, on the
reasonable-looking assumption that openbao-init's restore Job needs
openbao's own pod up first. Merged back 2026-08-12 after restoring ArgoCD's
real health check for nested Applications (infra repo's
`10-cluster/scaleway/argocd.tf`) turned that assumption into a real
deadlock: openbao's own Application health does not go Healthy until
openbao-init's restore has actually succeeded (true on every boot with a
reachable backup — only a truly from-scratch cluster with nothing to
restore skips this, and that one-time bootstrap procedure isn't automated
in this repo yet). With wave-gating now correctly waiting for real health,
openbao-init in a later wave than openbao meant wave 1 could never start
(waiting on wave 0's health) while wave 0 could never go healthy (waiting
on wave 1 to run) — chicken-and-egg. Fix: run them in the same wave, same
"brief intra-wave race, self-heals" tradeoff already accepted everywhere
else in this file — openbao-init's restore script just retries until
OpenBao is unsealed and reachable.

openbao-init has no ClusterSecretStore dependency, and conceptually never
did: this cluster's secret management is really two systems — OpenBao as
the internal Secret Store Manager's backend, ESO as its frontend — and
openbao-init is the one service that has to bootstrap itself before either
exists, since it's what makes both usable for everything else. That's why
its own credentials (the S3 Secret it restores from) are the one exception
in this whole architecture: Terraform-managed
(`10-cluster/scaleway/main.tf`'s `kubernetes_secret.scaleway_s3_credentials`),
not ESO-managed — it can't depend on the mechanism it exists to unlock. The
ClusterSecretStore itself physically lived in this chart's `templates/`
until 2026-08-12 (moved to `services/platform/secrets-sync/config`, see
that chart's own comment) — a file-location accident from early iteration,
not evidence this chart was ever meant to be coupled to ESO's mechanics.

## Wave 1 — external-secrets, secrets-sync, and every product's `*-secret`

**`external-secrets`/`secrets-sync` moved to the infra repo's
`platform-apps/values-secrets.yaml` wave 1 (infra#84, 2026-08-24)** — the
reasoning below for why they run one wave after OpenBao still applies
verbatim, just in that file now. `cert-manager-webhook-secret` and
`external-dns-secret` also moved (2026-08-25, scope extension) — to that
same repo's `platform-apps/values-networking.yaml` wave 0, alongside their
own consumers (`cert-manager`, `external-dns`) — a secret left behind here
would apply *after* its consumer already tried to start, since `bootstrap`
now runs after `networking-apps`, not before it. They keep the exact same
ESO/OpenBao `ExternalSecret` mechanism, unchanged — only which parent
Application owns them moved. Every other product's own `*-secret` chart
(dex-secret, grafana-secret, wireguard-secret, argo-workflows-secret) stays
right here, unaffected — those still need ESO/OpenBao, which is now
guaranteed Healthy even earlier than before (finishes ahead of `bootstrap`
starting at all, not just ahead of this wave). `thanos-secret`/`loki-secret`/
`tempo-secret`/`velero/secret` were deleted outright, not moved — see this
file's top note.

Two earlier designs were tried and dropped here, in order:

1. eso and secrets-sync split into separate waves (2026-08-12), on the
   theory that ESO being Healthy would mean it's ready to admit
   secrets-sync's manifests. Didn't close the gap: Application Healthy
   reflects "resources synced without error," not "the ClusterSecretStore
   CRD instance has reached its own Ready condition" — two different
   notions of health that don't automatically line up.
2. A dedicated `secrets-sync/verify` Job that polled the ClusterSecretStore
   for Ready before letting later waves proceed (2026-08-12/13) — worked,
   but only solved this for whatever sat immediately downstream of
   secrets-sync (velero). Every *other* product's own -init chart had the
   identical race against ESO, just one wave further out, and each would
   have needed the same verify-Job treatment individually.

Fixed at the source instead (2026-08-13): every chart that was ONLY an
ExternalSecret (velero/init, external-dns/init, wireguard/init,
cert-manager/webhook-init) renamed to `<product>/secret` and moved to wave
1, into the earliest wave that can possibly hold them — right alongside the
ESO/secrets-sync pair that makes ExternalSecrets work at all. Where a chart
mixed an ExternalSecret with something else (dex/init also had an
HTTPRoute; grafana-config also had a ConfigMap and, until the -gateway
split, an HTTPRoute too), the ExternalSecret was split out into a new
`<product>/secret` chart, leaving the original chart with just the non-secret
part in its own later wave. This maximizes the buffer ESO gets to actually
sync each real Secret before the product's own wave needs to mount it —
self-heals in seconds/minutes if a race still happens, same tradeoff every
other bundled wave here already accepts, and removes the need for a
dedicated verify Job per consumer.

## Wave 2 — argo-workflows, kube-prometheus-stack-crds

`argo-workflows` (2026-08-19, moved here 2026-08-20): the workflow-controller
AND server (`server.enabled`, 2026-08-20) — the server's SSO now dials Dex
in-cluster (`services/platform/argo-workflows/chart`'s `server.sso.issuer`),
so this has to sync after wave 1's dex, not share a wave with it.
terraform-apply (wave 6, needs this wave's CRDs Established before creating
a CronWorkflow CR — a hard, non-self-healing dependency at the API level,
same class as kube-prometheus-stack-crds → kube-prometheus-stack) is
unaffected: wave 2 still comfortably precedes wave 6.

**Moved to the infra repo's `platform-apps/values-monitoring.yaml` wave 0
(infra#84, 2026-08-24)** — along with the rest of monitoring (wave 3 below,
minus grafana). Reasoning below still applies verbatim, just in that file
now (renumbered wave 2→0 there, domain-local instead of global).

`kube-prometheus-stack-crds` (2026-08-13, previously an intentionally-unused
gap): the official prometheus-community/prometheus-operator-crds chart
(`services/platform/monitoring/crds`), pinned to the exact CRD version
kube-prometheus-stack 86.1.0/operator v0.91.0 ships (chart 29.0.0 → app
v0.91.0) — NOT the same chart as kube-prometheus-stack, a dedicated one
purely for these CRDs. A separate, earlier-wave Application purely so
ArgoCD's built-in CRD health check (the Established condition) gates
kube-prometheus-stack (wave 3, `skipCrds: true` so it doesn't also try to
own/prune these) from starting until they're genuinely ready, closing a
real live-observed race: prometheus-operator checks CRD availability
exactly once at pod startup (no watch, no retry), and can start a moment
before these CRDs finish establishing on the API server even though ArgoCD
already considers them Synced (apply-order isn't the same as
establishment-latency) — confirmed live 2026-08-13, the Prometheus custom
resource sat with an empty status forever, no operator log about it, no
StatefulSet, only fixed by a manual operator restart. Same mechanism as
gateway-config waiting on envoy-gateway/cert-manager's CRDs (wave 5). Moved
here from wave 6 the same day it was first added: monitoring's only real
prerequisites are OpenBao + ESO (wave 0/1), not cert-manager/gateway/dex
(waves 4-6) — nothing about those is actually needed for the
Prometheus/Grafana pods themselves to run, only for grafana-gateway's
HTTPRoute (which stays at wave 7).

## Wave 3 — kube-prometheus-stack, loki, tempo

**Moved to the infra repo's `platform-apps/values-monitoring.yaml` wave 1
(infra#84, 2026-08-24)** — reasoning below still applies verbatim, just in
that file now (renumbered wave 3→1 there). `thanos-secret` mentioned below
was deleted outright, not moved — see this file's top note.

Moved up from wave 7 (2026-08-13) for the same reason kube-prometheus-stack-crds
moved to wave 2: their real prerequisites are wave 2's CRDs (`skipCrds:
true` already set) and wave 1's secrets (thanos-secret).

Grafana itself moved OUT of this wave on 2026-08-14, into its own `grafana`
Application (wave 5) — its grafana-restore-* PreSync hook (Velero PVC
restore) needs the `velero` namespace/CRDs to exist first, and this wave
(3) runs before velero's wave (4).

`grafana-config` used to bundle in here too (its only content was a
TEMPORARY letsencrypt-staging CA bundle ConfigMap, needed while
gateway-config ran `letsencrypt-staging` — see that chart's own history
above/below). Removed entirely 2026-08-22: gateway-config has been back on
`letsencrypt-prod` since 2026-08-20, so the staging-only CA override was
dead weight (worse, actively wrong — it no longer matched the cert Dex
actually serves). See the matching removal in
`services/platform/monitoring/grafana-chart/values-scaleway.yaml`
(`auth.generic_oauth.tls_client_ca` + `extraConfigmapMounts`) and the
infrastructure repo's `10-cluster/scaleway/argocd.tf` (`oidc.config.rootCA`)
and `11-secrets/openbao/managed/main.tf`
(`oidc_discovery_ca_pem`) — same temporary CA, three consumers, removed
together.

loki / tempo: same "real prerequisite is wave 1's secret, not anything
cert-manager/gateway/dex-related" reasoning as kube-prometheus-stack — see
gitops#29.

## Wave 4 — argocd-config-monitoring

(Originally titled "velero, envoy-gateway, cert-manager, alloy,
otel-collector" — `velero` moved to the infra repo's
`platform-apps/values-backups.yaml` wave 0, `alloy`/`otel-collector` moved
to that repo's `platform-apps/values-monitoring.yaml` wave 2 (infra#84,
2026-08-24), and `envoy-gateway`/`cert-manager`/`cert-manager-webhook-scaleway`
moved to that repo's `platform-apps/values-networking.yaml` wave 1
(2026-08-25, scope extension). `argocd-config-monitoring` is the only app
still in this wave — kept as its own wave rather than renumbered down,
same "gaps are cheap" reasoning as always. The reasoning below for why
velero/envoy-gateway/cert-manager/alloy/otel-collector didn't need their
own wave is kept for context — it doesn't apply to where they live now,
since that's a different chart/parent Application entirely, not just a
different wave number.)

velero + envoy-gateway + cert-manager (+ its Scaleway DNS01 ACME webhook):
these three don't depend on each other at all — velero was in its own wave
3 only because it happened to be added first, not because anything
downstream needed it separate from envoy-gateway/cert-manager. What
actually needs all three is gateway-config (wave 5): velero for its
cert-restore PreSync hook (restoring the TLS cert backup from Velero's own
S3 bucket), envoy-gateway for the Gateway API CRDs, cert-manager for the
cert-manager.io CRDs its ClusterIssuers need. Since gateway-config already
waits a full wave for all three regardless of how they're split amongst
themselves, merging velero in here removed a wave for free — wave "3" was
left unused rather than renumbering everything from 4 onward. Both gaps
got filled 2026-08-13 by kube-prometheus-stack-crds/kube-prometheus-stack
moving up from waves 6/7 — this wave's own numbering still didn't need to
shift, which was the point of leaving the gaps cheap to fill rather than
renumbering.

envoy-gateway and cert-manager only race each other softly: cert-manager's
own chart creates no Gateway-API-typed object (its `gatewayAPI.enabled` is
a runtime controller flag, not a CRD dependency at sync time) — its "Gateway
API CRDs do not seem to be present" crash (confirmed live 2026-08-11/12) is
the controller *pod* checking at startup and restarting, which kubelet
retries on its own indefinitely, same "brief intra-wave race, self-heals"
tradeoff every other bundled wave here accepts. That's categorically
different from gateway-config's own hard dependency (wave 5) — no reason to
give cert-manager its own wave too. The webhook found live 2026-08-11 to
have the exact same OpenBao-secret race as Velero/external-dns/Dex, just
via a different values key (`secret.externalSecretName`) that the original
fix's grep pattern missed. That webhook deployment doesn't need
cert-manager's own CRDs to exist (it's just a Deployment/Service/APIService
registration — cert-manager, same wave, is the CONSUMER of this webhook via
the extension API it registers, not the other way around), so it's fine
bundled here too.

alloy / otel-collector: one wave after loki/tempo (wave 3) — both need the
`loki`/`tempo` Services resolvable, not just created. Unrelated to
velero/envoy-gateway/cert-manager; sharing this wave is free the same way
those three already coexist here. See gitops#29.

argocd-config-monitoring (2026-08-20): PrometheusRule, needs wave 2's
kube-prometheus-stack-crds Established first (the monitoring.coreos.dev
CRDs) — shares this wave for the same "no interdependency, wave reuse is
free" reasoning as everything else here.

## Wave 5 — grafana

(`gateway-config` moved to the infra repo's
`platform-apps/values-networking.yaml` wave 2, 2026-08-25 — the reasoning
below for why it needs its own wave, one past envoy-gateway/cert-manager's
CRDs, still applies verbatim there. `grafana` is the only app left in this
wave.)

gateway-config needs BOTH envoy-gateway (Gateway API CRDs, for its
own Gateway/GatewayClass/HTTPRoute) AND cert-manager
(cert-manager.io CRDs, for its ClusterIssuers) to have actually finished
installing their CRDs. Unlike cert-manager's own race, this one is
a genuinely hard dependency: gateway-config's ClusterIssuer objects are
themselves cert-manager.io-typed resources — if that CRD type isn't
registered yet, ArgoCD's sync fails outright at the API level ("could not
find cert-manager.io/ClusterIssuer... Make sure the CRD is installed"),
confirmed live 2026-08-12: 5 retries exhausted, never self-healing on its
own, unlike every pod-level crash-loop race this file otherwise tolerates.
That's why gateway-config can't share a wave with the very
CRDs it depends on — it needs them to have actually landed first.

grafana (added 2026-08-14, split out of wave 3's kube-prometheus-stack)
joins here for a narrower reason than gateway-config's: it doesn't need
envoy-gateway/cert-manager's CRDs at all, only Velero (infra#84,
2026-08-24: now the infra repo's `backups-apps` domain, guaranteed Healthy
before `bootstrap` even starts syncing — strictly earlier than "wave 4" was)
— its grafana-restore-* PreSync hook
(`services/platform/velero/chart/values-scaleway.yaml`'s grafana-data
schedule) does `kubectl get backup/restore -n velero`, which needs the
`velero` namespace and velero.io CRDs to actually exist, not just be
mid-install. Reuses this wave rather than inventing a new one, same
"gaps/later waves are cheap to reuse, don't renumber for a narrower
dependency" logic as wave 4's own history. No `syncWaveLabelPaths` here
(unlike its siblings) — grafana-chart hardcodes its wave label directly
(`values-scaleway.yaml`'s own comment on `podLabels` explains why: the
inject-via-Helm-parameter mechanism every other app here uses produced a
live-broken manifest for this specific chart).

<!-- historical: `terraform-apply` below was replaced wholesale by Crossplane
     + provider-opentofu (infra#101). It no longer exists as a chart or a
     wave; the wave-6 reasoning here is kept only as the record of why the
     CronWorkflow approach was placed where it was. -->

## Wave 6 — wireguard-config, dex-gateway, terraform-apply

(`external-dns` moved to the infra repo's
`platform-apps/values-networking.yaml` wave 2, 2026-08-25 — alongside
`gateway-config`, which it "rode along" with here for the same reason
described below.)

dex-gateway needs the infra repo's networking-apps domain's gateway-config
to have actually finished reconciling — it's HTTPRoute-only (its
ExternalSecret moved to dex-secret, wave 1; the Dex server itself moved up
to wave 1 too, 2026-08-20), so it needs the Gateway its HTTPRoute binds to.
external-dns didn't strictly need the Gateway itself (its own DNS-record
reconciliation is soft/eventually-consistent, not a hard CRD-registration
dependency like gateway-config's ClusterIssuer was) but rode along in this
wave rather than getting its own — no observed race — before it moved out
entirely.

wireguard-config originally needed to wait here too, for the same reason
dex-gateway does: its proxy-gateway sidecar discovered the Service
envoy-gateway provisions once gateway-config's Gateway object exists
(confirmed live 2026-08-12: crash-loops on an empty `kubectl get svc -l
gateway.envoyproxy.io/owning-gateway-name=scaleway-gateway` otherwise).
That sidecar was removed 2026-08-24 (infrastructure#81 — internal-cluster
DNS + a `proxy-dynamic` sidecar replaced it, resolving targets live via
CoreDNS instead of listing them or the K8s API, no Gateway API dependency
at all) — wireguard-config no longer strictly needs this wave,
but stays here for now, same "rides along, no observed race" reasoning
external-dns used to have.

dex-gateway was renamed twice on 2026-08-13: first dex-init → dex-config
(still imprecise — "config" doesn't say what it actually creates), then
dex-config → dex-gateway once every other HTTPRoute-only/HTTPRoute-containing
chart got the same "-gateway" treatment for the same reason the
ExternalSecret-only charts became "-secret": name it for the Gateway-API
resource it actually creates, not a generic "config"/"init". Same pattern
applied to `services/platform/openbao/gateway` (renamed from
`openbao/config`, also HTTPRoute-only) and to
`services/platform/monitoring/grafana-gateway` /
`services/platform/argocd-config/gateway` — new charts split out of
`grafana-config` / `argocd-config/config`, which kept their name since
what's left in them (ExternalSecrets, RBAC, the restart hook) is genuinely
just "config", not HTTPRoute. Unlike the *-secret rename, this one isn't
fixing a race (HTTPRoute's binding to a Gateway is already
soft/eventually-consistent, no wave-timing issue observed) — it's purely
naming precision, so these charts keep whatever wave their parent already
had.

wireguard-exit-config doesn't actually need to wait on gateway-config (no
dependency on the shared Gateway at all — same as wireguard-config now,
above) — it would ride along in the same wave as its sibling anyway for
simplicity if enabled; nothing forces it any earlier.

terraform-apply: REMOVED (issue #101). The hand-rolled Argo Workflows
CronWorkflows that ran `tofu apply` for openbao-managed and grafana-managed
were replaced by Crossplane + provider-opentofu `Workspace` CRs
(`services/platform/crossplane`), driven from the infra repo's
`crossplane-apps` platform-apps tier with its own per-root health gating
(`wait_secrets_healthy` / `wait_grafana_healthy`) — so the wave-placement
problem this paragraph used to describe no longer exists. grafana-bootstrap
went too (its minted token could rot after a restore); grafana-managed now
authenticates as Grafana's admin directly.

## Wave 7 — every remaining `*-gateway` chart

argocd-config/openbao-gateway ride along together: same prerequisite
(Gateway + Dex from wave 6), no named stage of their own.
argocd-config-gateway is the HTTPRoute half split out of argocd-config's
config chart (see wave 6's `-gateway` rename history) — same wave as the
chart it split from, this rename didn't change any ordering.

grafana-gateway (monitoring's own HTTPRoute) also stays here — moved
2026-08-13 to be the ONLY monitoring app left in this wave (see waves 2/3
for where the rest of monitoring went): its real dependency is the shared
Gateway (now the infra repo's networking-apps domain) + Dex (wave 6) it
binds to, same as every other *-gateway chart in this wave, not OpenBao/ESO.

argo-workflows-gateway (2026-08-20): same "real dependency is Gateway + Dex
from wave 6" reasoning as every other *-gateway chart in this wave —
exposes the Argo Server UI/API enabled in
`services/platform/argo-workflows/chart`.

## Wave 8 — products

`demo` and any future product chart. No platform dependency beyond
everything already being up by this point.
