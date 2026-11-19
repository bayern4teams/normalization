# ADR-024: The App Machine and Private Releases

## Status

Accepted — 2026-11-19. Owner decisions of 2026-11-19, quoted below.

## Context

The app ran on the owner's laptop: the API with its UI, its own Postgres, and a libpostal
container, beside other apps that share the laptop's memory. The databases the app clones live
on the benchmark box (10.10.9.41), a virtual machine that already runs libpostal on port 6901.
Releases existed only as a GitHub workflow on milestone tags that was never run, and it signed
images keylessly, which writes to the public Sigstore log.

## Decision

**One machine runs the app, and only the app.** "app is go to module machine that only run app.
this machine it takes responsibility that my pc now it have." `deploy/compose.yaml` runs two
services there: the API (the UI built in) and the app's own Postgres ("4. a"). The demo
databases stay in the development `compose.yaml` ("2. a").

**libpostal stays on the benchmark box, as a setting.** "that box is vm for external databases.
so libpostal should be there ... but should be dynamic. change port or address". Its URL is
`NORM_LIBPOSTAL_URL` in `deploy/.env`.

**Every address, port and password is a setting.** "we should have this dynamic that we could
add or change connection or ssh or api". Saved connections change at run time in the UI or the
API, as before. Every other value lives in `deploy/.env`; a change takes `docker compose up -d`,
a restart of about 30 seconds ("2. a" of the second batch). "ssh" means only that the owner
manages the machine over SSH; the app gets no SSH tunnels ("1. a").

**Released images, pulled, never built on the machine.** Old question "3 is a". The source is
on the machine too, cloned from the owner's remotes.

**A release is a `vX.Y.Z` tag, on both remotes** ("4. a"). It publishes the API image to the
remote's own container registry and the Python packages (wheels and source archives) with a
release ("5. a"). The tag must equal every package's version
(`scripts/check_release_version.py`).

**Nothing is public.** "note that nothing should be public at all." Images, packages and
releases take the private repository's visibility. Images are not signed: keyless signing
publishes to the Sigstore transparency log.

**The laptop's app database moves with its key.** Old question "6 is a": the saved connections,
job history and review queue are copied with `pg_dump`, and `NORM_SECRET_KEY` goes with them.

**The owner works the machines; the agent writes the guide.** "what you should guide me i do it
myself", "you should only guide me step by step". The guide is `docs/DEPLOY.md`.

## Consequences

- The milestone tags no longer publish anything. Their sign-off gate stays in the milestone
  pipelines (`gate.yml`, `.gitlab-ci.yml`).
- The GitLab release jobs use docker-in-docker, which this runner has not run yet; the first
  tag is their first test.
- No image signature: the machine trusts the registry login. Add signing with a private key if
  that stops being enough.
- The libpostal image is not released: the box runs its own.
