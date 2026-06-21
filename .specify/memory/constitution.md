# Scalepack Constitution

Principes non négociables de la plateforme Scalepack, par ordre de priorité.
Cette constitution prime sur toute autre pratique.

## Core Principles

### I. Low-cost, OSS-first
La plateforme SHALL tourner exclusivement sur des composants open-source ou en
tier gratuit. Aucun service tiers payant n'est adopté sans l'accord explicite de
l'humain. À fonctionnalité équivalente, l'option self-hosted open-source l'emporte.

### II. Humain seul décisionnaire sur l'outillage
Toute techno, dépendance ou service proposé SHALL être présenté à l'humain avec
ses alternatives avant adoption. L'agent ne décide jamais seul d'un choix
d'outillage.

### III. Standard entreprise
Auditabilité, isolation des tenants et gouvernance des coûts sont des
préoccupations de premier ordre sur chaque feature. La plateforme SHALL traiter
ces trois axes comme des exigences, pas des options.

### IV. Validation par étapes (NON-NEGOCIABLE)
Une tâche ne passe à l'état terminé que si ses prérequis sont remplis ET son
critère d'acceptation (« Done quand ») est vérifié. Pas de raccourci.

### V. GitOps-first
Tout artefact de décision (spec, plan, tasks, constitution) SHALL être versionné
en git. Aucune config ne vit hors du repo.

### VI. Souveraineté par défaut
Scaleway (souverain, européen) SHALL être le provider par défaut, dans l'esprit
OSS-first du Principe I. Un compromis (AWS ou autre) n'est adopté QUE lorsque
Scaleway est réellement complexe/impossible, et UNIQUEMENT après un retour honnête
(le vrai trade-off, sans enrobage) puis la validation de l'humain (cf. Principe II).
L'agent ne suppose jamais AWS par défaut. Exemple de compromis acté : le backend
d'état Terraform sur AWS S3 (`00-remote_state`), faute d'équivalent Scaleway propre.

### VII. Acceptation vérifiable en CI (NON-NEGOCIABLE)
Tout critère d'acceptation (« Done quand ») SHALL être prouvable par la CI : soit
exécuté directement en CI, soit vérifié par une CI qui interroge une ressource ou un
conteneur déployé éphémèrement sur une branche de dev. Aucune validation manuelle
n'est recevable. Ce principe renforce le Principe IV.

## Conventions d'écriture

- Les requirements de specs s'écrivent en **notation EARS** (voir `CONVENTIONS.md`).
- Les items de roadmap déclarent toujours `Done quand:` et `Dépend de:`.

## Architecture multi-repo

- **Lecture/exploration cross-repo, écriture mono-repo.** On planifie depuis
  l'orchestration en lisant partout ; on implémente toujours dans un seul repo à
  la fois (une PR).
- La roadmap cross-repo vit dans `.taskmaster/` du repo d'orchestration.

## Governance

Cette constitution prime sur toutes les autres pratiques. Tout amendement SHALL
être documenté, approuvé par l'humain, et versionné en git. Chaque PR/revue SHALL
vérifier la conformité à ces principes. Toute complexité ajoutée SHALL être
justifiée au regard du Principe I (low-cost) et du Principe III (standard entreprise).

**Version**: 1.1.0 | **Ratified**: 2026-06-20 | **Last Amended**: 2026-06-20
