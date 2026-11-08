# Repository boundary

This public core owns verification contracts, HTTP API, deterministic planning,
profile/rule execution, evidence/coverage semantics, local runner, optional Temporal
integration, reference tests and basic visual capture/comparison.

A future private hosted extension owns provisioning, organization roles/subscriptions,
billing, managed execution/storage integrations and enterprise operations. Do not
create a second cloud repository until there is distinct code to own. Existing
MetaForge-Cloud identity may be integrated through the Authenticator seam.

Dependency direction:
- MetaForge submits immutable revisions using the public HTTP contract.
- Verification remains usable by other engineering clients.
- Cloud extensions import this core and inject provider implementations.
- Core never imports MetaForge's gateway, Supabase client or a private repository.

The core uses Apache-2.0, matching MetaForge. Existing third-party tools and assets keep
their own licenses. No customer designs, production secrets or private datasets belong
in this repository.

## Publishing the prepared repository

This workspace contains a complete source tree and a local initial git commit. The
connected GitHub tools could not create a repository. Once an empty public repository
has been created and access granted, push this source tree; no existing MetaForge
repository needs to be renamed or overwritten.

Source ZIPs exclude `.git`. If starting from the ZIP, initialize and commit first:

```bash
git init -b main
git add .
git commit -m "Initial verification core"
```

Then use your authenticated GitHub CLI from the source directory:

```bash
gh repo create FidelOdok/MetaForge-Verification --public --source=. --remote=origin --push
```

If the repository already exists, add its verified remote and push the prepared main
branch instead. Do not run the create command against an existing nonempty repository.
