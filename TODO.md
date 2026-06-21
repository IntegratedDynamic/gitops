# TODO

## OpenBao — ce qui reste à faire

### 1. Sortir du mode `dev`

`platform/local/openbao.yml` a encore `dev: enabled: true`.  
Ce mode est in-memory, sans Raft, sans seal — inutilisable en prod.

- [ ] Passer en mode standalone avec Raft réel (supprimer `dev: enabled: true`, garder la config `standalone.config` déjà présente)

---

### 2. Auto-unseal — **Option C choisie : AWS KMS natif**

Scaleway KMS n'est pas supporté nativement par OpenBao (pas d'API AWS KMS-compatible, pas de PKCS#11). On part sur AWS KMS natif (hors Scaleway).

- [x] **Terraform KMS** — `infrastructure/03-backup/scaleway/kms.tf` : clé KMS symétrique (rotation auto, `prevent_destroy`), user IAM dédié single-purpose (Encrypt/Decrypt/DescribeKey via key policy, aucune policy IAM), access key statique. Outputs : `openbao_unseal_kms_key_id`, `openbao_unseal_aws_region`, `openbao_unseal_access_key_id`, `openbao_unseal_secret_access_key`.
  - ⚠️ **Apply = admin/local uniquement** (`aws sso login`). Le rôle CI backup est S3-only et la permissions-boundary interdit les users IAM + access keys → un push touchant `kms.tf` fait échouer le CI `backup_scaleway`.
- [ ] **Côté gitops** — ajouter le stanza `seal "awskms"` dans `standalone.config` de `platform/<env>/openbao.yml` (`region`, `kms_key_id`) + injecter `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` dans le pod OpenBao via un Secret (`extraSecretEnvironmentVars` ou env). Chicken-and-egg : ce Secret ne peut PAS venir d'OpenBao lui-même → source externe (bootstrap cluster terraform, ou Infisical→ESO pendant la transition).
- [ ] **Init** — avec auto-unseal, `bao operator init` génère toujours des recovery keys (Shamir de secours) : les stocker hors-cluster.

---

### 3. Snapshot agent — prérequis OpenBao

La config S3 est posée (`platform/local/openbao.yml`), mais le CronJob ne peut pas s'authentifier à OpenBao sans :

- [ ] Activer le Kubernetes auth method dans OpenBao :
  ```bash
  bao auth enable kubernetes
  bao write auth/kubernetes/config kubernetes_host=https://kubernetes.default.svc
  ```
- [ ] Créer la policy `snapshot` (droit sur `sys/storage/raft/snapshot`)
- [ ] Créer le role `snapshot` lié au ServiceAccount du CronJob :
  ```bash
  bao write auth/kubernetes/role/snapshot \
    bound_service_account_names=openbao-snapshot-agent \
    bound_service_account_namespaces=openbao \
    policies=snapshot \
    ttl=1h
  ```

---

### 4. Restauration au démarrage (non natif) — **implémenté, en attente de validation E2E**

Le snapshot agent fait des backups, mais ne restaure pas au boot.  
Pour un cluster éphémère, il faut un job d'init qui :

- [x] Vérifie si OpenBao est fraîchement initialisé (`bao operator init -status`)
- [x] Télécharge le dernier snapshot depuis `s3://backup-dev-id`
- [x] Exécute `bao operator raft snapshot restore <snapshot>`

Réalisé via `apps/openbao-init/` : Job-hook ArgoCD (`hook: Sync`,
`hook-delete-policy: BeforeHookCreation`) qui miroir le script de backup upstream
dans la même image `openbao-snapshot-agent` (`bao` + `s3cmd`). Idempotent : ne touche
jamais un cluster déjà initialisé. Sur cluster vide → `bao operator init` (token root
jetable, juste le temps du restore) puis `snapshot restore`. **Local uniquement**
(scaleway hors scope, pas encore de snapshots).

- [ ] Smoke test : `mise run reset && mise run dev`, vérifier qu'un secret témoin
      survit au reset. Vérifier aussi que le nœud se re-unseal seul après restore
      (même clé KMS) — sinon redémarrer `openbao-0`.

---

## Ce qui est fait

- [x] `snapshotAgent` configuré dans `platform/local/openbao.yml` — pousse vers `s3://backup-dev-id` (Scaleway fr-par) toutes les 5 min
- [x] Credentials S3 injectés via Secret `scaleway-s3-credentials` (créé par Terraform, pas dans git)
