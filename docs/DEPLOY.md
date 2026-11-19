# Move the app to the app machine

This guide moves the app from the laptop to its own machine, the **app machine**. Afterwards the
app machine runs the app and nothing else. The benchmark box keeps the databases you clone and
libpostal. Why it is built this way: [ADR-024](adr/ADR-024-app-machine-and-private-releases.md).

| Machine | Runs |
|---|---|
| App machine | The API with its UI, and the app's own database (`deploy/compose.yaml`) |
| Benchmark box (10.10.9.41) | The databases you clone, and libpostal on port 6901 |
| Laptop | Nothing of the app. You open the UI in a browser. |

Every command says where it runs: **[laptop]**, **[app machine]**, **[box]** or **[GitHub]** /
**[GitLab]** (the web page). Text in `<angle brackets>` is yours to fill in.

## 1. Prepare the app machine

1. **[app machine]** Install Docker Engine with the Compose plugin and git, from Docker's own
   guide for your Linux. Check: `docker compose version` prints 2.24 or later.
2. **[app machine]** Give it at least 6 GB of memory and 20 GB of free disk. The API is
   capped at 4 GB (`NORM_MEM_LIMIT`), and its Postgres needs the rest.
3. Write down its private network address, for example `10.10.9.50`. This guide calls it
   `<app address>`.

## 2. Let the app machine reach the box

The box drops new connections to its database and libpostal ports from every host except the
laptop (`/home/benchmark/README.md`, "Machine facts"). Without this step, the app cannot clone
anything and address parsing fails.

1. **[box]** Add `<app address>` to the rules of `bench-docker-firewall.service`, the same way
   the laptop's address 10.10.9.137 is allowed there. Restart the service.
2. **[app machine]** Check: `curl -s http://10.10.9.41:6901/health` answers.

## 3. Make the first release

A release builds the image the app machine runs. It is private on both remotes.

1. The version in every `pyproject.toml` must equal the tag. Today they are `0.1.0`, so the
   first tag is `v0.1.0`. A later release: change every version, commit, then tag.
2. **[laptop]**, in the repository, on `main`:

   ```bash
   git tag -a v0.1.0 -m "v0.1.0"
   ```

   ```bash
   git push origin v0.1.0
   ```

   `origin` pushes to GitLab and GitHub both.
3. **[GitHub]** Actions, workflow "release": wait for green. The image is
   `ghcr.io/bayern4teams/normalization/api:v0.1.0`.
4. **[GitHub]** Your profile, Packages, `normalization/api`, Package settings: check that the
   visibility says **Private**.
5. **[GitLab]** CI/CD, Pipelines, the tag's pipeline: wait for the release stage to finish.
   The image is in Deploy, Container Registry; the packages are in Deploy, Package Registry.
   Write down the registry address the Container Registry page shows.

## 4. Give the app machine read-only access

Create a token that can only read, one remote is enough.

- **GitHub:** Settings, Developer settings, Personal access tokens (classic), new token with
  only `read:packages` and `repo`.
- **GitLab:** the project, Settings, Repository, Deploy tokens, new token with
  `read_repository` and `read_registry`.

Then **[app machine]**, once:

```bash
docker login ghcr.io -u <github user>
```

or, for GitLab:

```bash
docker login <gitlab registry address> -u <deploy token user>
```

Paste the token when asked. Docker stores it for later pulls.

## 5. Get the source and the settings

1. **[app machine]**

   ```bash
   git clone <repository URL> ~/normalization
   ```

   Use the same token as the password when git asks.
2. **[app machine]**

   ```bash
   cd ~/normalization/deploy && cp .env.example .env && chmod 600 .env
   ```

3. Fill in `deploy/.env`. Each line is explained in the file.
   - `NORM_IMAGE`: the image from step 3, for example
     `ghcr.io/bayern4teams/normalization/api:v0.1.0`.
   - `NORM_BIND_ADDR`: `<app address>`.
   - `NORM_DB_PASSWORD`: a new random string, for example from `openssl rand -hex 24`.
   - `NORM_SECRET_KEY`: **[laptop]** copy the value of this line from the repository's `.env`.
     It must be the same key, or the saved connections cannot be read.
   - `NORM_LIBPOSTAL_URL`: `http://10.10.9.41:6901`.

## 6. Move the app's data

The app's own database holds the saved connections, the job history and the review queue.

1. **[laptop]**, in the repository:

   ```bash
   docker compose up -d --wait postgres
   ```

   ```bash
   mkdir -p ~/normalization-move && docker compose exec -T postgres pg_dump -U normalization -Fc normalization > ~/normalization-move/app-db.dump && chmod 600 ~/normalization-move/app-db.dump
   ```

2. **[laptop]** Copy it over:

   ```bash
   scp ~/normalization-move/app-db.dump <user>@<app address>:~/app-db.dump
   ```

3. **[app machine]**, in `~/normalization/deploy`, start only the database and load the copy,
   before the app starts for the first time:

   ```bash
   docker compose --env-file .env up -d --wait postgres
   ```

   ```bash
   docker compose exec -T postgres pg_restore -U normalization -d normalization --no-owner < ~/app-db.dump
   ```

4. **[app machine]** Check that the count is the number of connections the laptop had:

   ```bash
   docker compose exec postgres psql -U normalization -tc "select count(*) from normalization_connections"
   ```

The dump holds encrypted passwords and real data values. Delete both copies after the app runs
(step 8).

## 7. Start the app

**[app machine]**, in `~/normalization/deploy`:

```bash
docker compose --env-file .env pull
```

```bash
docker compose --env-file .env up -d --wait
```

Check:

- `docker compose ps` shows both services `healthy` after about 30 seconds.
- `curl -s http://<app address>:8080/health` prints `{"status":"ok"}`.
- **[laptop]** open `http://<app address>:8080` in the browser. Connections lists your saved
  connections, and New clone lists the databases of one of them on the box.

## 8. Retire the laptop's copy

1. **[laptop]** Stop the app there, and its database: `docker compose down` in the
   repository. The data stays in the Docker volume until you delete it.
2. Delete `~/normalization-move/app-db.dump` **[laptop]** and `~/app-db.dump`
   **[app machine]**.

## Daily work

| Task | On the app machine, in `~/normalization/deploy` |
|---|---|
| Change a setting (libpostal address, port, memory) | edit `.env`, then `docker compose --env-file .env up -d` |
| Add, change or remove a database connection | in the UI, Connections. To change one: remove it and add it again. |
| Update to a new release | set `NORM_IMAGE` to the new tag, then `pull` and `up -d` as in step 7 |
| Roll back | set `NORM_IMAGE` to the old tag, then `up -d` |
| Update the source | `git pull` in `~/normalization` |
| Back up the app's data | `docker compose exec -T postgres pg_dump -U normalization -Fc normalization > backup-$(date +%F).dump` |
| See what the app does | `docker compose logs -f api` |

When something fails: `docker compose ps` and `docker compose logs --tail=100 api` name the
setting or the address that is wrong.
