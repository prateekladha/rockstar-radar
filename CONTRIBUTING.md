# Contributing

`main` is protected and deploys to production (https://intraday.live). **No one pushes to `main`
directly** — every change goes through a pull request.

## Workflow

1. **Branch** off `main`: `git checkout -b feat/your-change`
2. **Open a PR** against `main`.
3. **CI runs automatically** (`.github/workflows/ci.yml`): it builds the frontend (`npm ci && npm run
   build`) and installs + imports the backend. The PR **cannot be merged until this passes**.
4. **One approval** is required before merging.
5. **On merge, prod deploys automatically** (`.github/workflows/deploy.yml`): a self-hosted runner on
   the OCI VM syncs `main`, rebuilds the image, restarts the stack, and health-checks the site. If the
   health check fails, the deploy job goes red.

## Notes

- Repo admins can push directly to `main` in an emergency (branch protection excludes admins), but the
  normal path for everyone — including admins — is a PR.
- The deploy runner lives on the production VM and connects out to GitHub; there are no OCI secrets in
  GitHub and the Bastion stays locked.
- Secrets never go in the repo — they live in OCI Vault and are fetched into RAM at boot.
- Keep trading-critical changes (engine, scanner, order flow) small and reviewed; this app places real
  orders behind user confirmation.
