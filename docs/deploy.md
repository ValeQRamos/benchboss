# Deploying benchboss

This page is the runbook for putting benchboss on a server and keeping it up to date: the
first deploy, updates, rollbacks, adding people, and an automatic deploy from GitHub.
[server.md](server.md) explains the pieces (SSH keys, cookies, the sign in page); this page is
the order to do things in.

Everything below was run against a real 512 MB Ubuntu 24.04 server. Nothing here is needed to
use benchboss on your own computer.

## How it fits together

```mermaid
flowchart LR
    GH[GitHub: main] -->|CI passes| A[Deploy job]
    A -->|SSH, restricted key| U[update.sh on the server]
    U --> R["/opt/benchboss/releases/ID/"]
    R -->|current symlink| S1[benchboss-web@alice]
    R -->|current symlink| S2[benchboss-web@bob]
    S1 --> C[Caddy: HTTPS]
    S2 --> C
```

| Piece | What it is |
|---|---|
| `/opt/benchboss/releases/<id>/` | One Python environment per version. Each deploy builds a new one. Four are kept. |
| `/opt/benchboss/current` | A symlink to the live release. Switching versions, and going back, is changing this link. |
| `/opt/benchboss/update.sh` | Builds a release, switches, health-checks every web instance and **rolls back by itself** if one does not answer. |
| `benchboss-web@NAME` | One web app per person. `NAME` is a Linux user with their own ESPN account, settings and sign in password. |
| `/etc/benchboss/NAME.env` | That person's port, public address and optional GitHub options. Readable only by root. |
| `benchboss-users` | Adds, lists and removes people. |

## First deploy

You need a server (section 1 to 3 of [server.md](server.md): create it, add your SSH key,
paste the provisioning script) and a name that points at it. Replace `SERVER_IP` and
`NAME` below. A free name that always works is the IP with dashes, for example
`203-0-113-7.sslip.io` for `203.0.113.7`.

**1. Check you can log in.**

```bash
ssh -i ~/.ssh/benchboss_ssh bb@SERVER_IP 'echo ok'
```

**2. Prepare the server.** From a clone of this repository on your computer:

```bash
export SSH_OPTS="-i $HOME/.ssh/benchboss_ssh"
deploy/deploy.sh bootstrap bb@SERVER_IP
```

This installs `uv`, the release folder, the `benchboss-users` tool and the service template,
and adds a 1 GB swap file on small servers. It is safe to run again.

**3. Deploy a version.**

```bash
deploy/deploy.sh update bb@SERVER_IP
```

With no version it deploys the commit you are on. If that commit is on GitHub the server
downloads it from there; if not, your local copy is sent instead. Check it:

```bash
deploy/deploy.sh status bb@SERVER_IP
ssh -i ~/.ssh/benchboss_ssh bb@SERVER_IP 'benchboss --version'
```

**4. Add the first person** (yourself). On the server:

```bash
sudo benchboss-users add bb --existing --url https://SERVER-IP-WITH-DASHES.sslip.io
```

`--existing` uses your current Linux user. For a new person, leave it off (see
[Adding people](#adding-people)). The command starts the web app and prints the Caddy block to
add. Their sign in password is in `/home/NAME/.bb-web-password`.

**5. Put HTTPS in front.**

```bash
sudo apt-get install -y caddy
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo nano /etc/caddy/Caddyfile      # paste the block that step 4 printed
sudo systemctl reload caddy
```

**6. Give the server your ESPN cookies.** From your computer:

```bash
benchboss login --to bb@SERVER_IP --identity ~/.ssh/benchboss_ssh
```

Or skip this: the first time you sign in on the web page, a setup screen asks for the two
cookies (`espn_s2` and `SWID`).

**7. Check it from outside.** From your computer, not the server:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://YOUR-NAME/login           # 200
curl -s -o /dev/null -w '%{http_code}\n' https://YOUR-NAME/ws              # 401: no session, no app
curl -s -m 5 -o /dev/null -w '%{http_code}\n' http://SERVER_IP:8000/       # 000: the raw port is closed
```

Then open `https://YOUR-NAME` in a browser and sign in as `owner` with the password from
`sudo cat /home/NAME/.bb-web-password`.

## Updating and rolling back

```bash
deploy/deploy.sh update bb@SERVER_IP            # the commit you are on
deploy/deploy.sh update bb@SERVER_IP v1.2.0     # a tag, a branch or a full commit sha on GitHub
deploy/deploy.sh update bb@SERVER_IP --local    # always send your local copy
deploy/deploy.sh status bb@SERVER_IP            # the live release and the ones kept
deploy/deploy.sh rollback bb@SERVER_IP          # go back one release (a few seconds)
```

What an update does:

1. Downloads the source and builds it into a new folder. Nothing live changes yet. If the build
   or `benchboss --version` fails, the update stops here.
2. Points `current` at the new release and restarts every running web app.
3. Asks each app's sign in page for an answer for up to 40 seconds.
4. If any app does not answer, it points `current` back, restarts, and moves the broken release
   to `/opt/benchboss/failed/` for you to look at. The update exits with an error.

Expect the apps to be unreachable for a few seconds during a restart, and for about 40 extra
seconds when a release fails and is rolled back. Browser sessions in progress end, and people
sign in again only if their 12 hours ran out.

To see why a release failed:

```bash
ls /opt/benchboss/failed/
sudo journalctl -u 'benchboss-web@*' --since '10 minutes ago' --no-pager | tail -40
```

## Adding people

One person is one Linux user with their own ESPN account. Their settings, cookies and sign in
password live in their own home folder and other users cannot read them. All run the same
installed version.

```bash
sudo benchboss-users add alice --url https://alice.SERVER-IP-WITH-DASHES.sslip.io
```

(With sslip.io any label in front of the dashed IP works, so every person gets a name of their
own on one server. With your own domain, add a DNS record per person.)

It creates the user, a random password, picks a free port, starts the app and prints the Caddy
block. Then:

1. Add the block to `/etc/caddy/Caddyfile` and run `sudo systemctl reload caddy`.
2. Give the person three things: the address, the user name `owner` and the password from
   `sudo cat /home/alice/.bb-web-password`. Send the password over a private channel, not a
   shared chat.
3. They sign in. Because they have no cookies yet, a setup screen asks for their `espn_s2` and
   `SWID`, then their league and team.

Other things you can do:

```bash
sudo benchboss-users list                      # everyone, their port, state and address
sudo benchboss-users password alice            # a new password (old sessions end when they expire)
sudo benchboss-users remove alice --yes        # stop the app and delete the user and ALL their data
```

After `remove`, delete their block from the Caddyfile and reload Caddy.

**Sign in with GitHub for a person.** Register an OAuth app on GitHub (Settings, Developer
settings, OAuth Apps, New) with the person's address as homepage and
`https://THEIR-ADDRESS/login/github/callback` as callback URL. GitHub allows one callback per
OAuth app, so each address needs its own app. Then:

```bash
sudo benchboss-users github alice --client-id THE_CLIENT_ID --users alicelogin
```

It asks for the client secret with hidden input. Only the GitHub users you list can sign in,
and each one acts as that person's ESPN account, so list only people who should.

**Terminal access for a person** (optional, not needed for the web page): add their SSH public
key to their account. They get a shell as themselves, without `sudo`.

```bash
sudo -u alice install -d -m 700 /home/alice/.ssh
echo 'ssh-ed25519 AAAA...their-key... alice-laptop' | sudo -u alice tee -a /home/alice/.ssh/authorized_keys
```

**Your own devices** (a new phone or laptop for the admin user `bb`): add its public key to
`/home/bb/.ssh/authorized_keys`. To remove a device, delete its line.

**How many people fit.** Every open browser tab runs its own app process of about 70 MB, and
each person's apps are capped at 350 MB. A 512 MB server is comfortable for one or two people;
use 1 GB or more for more. If memory runs out the capped app is restarted and the server stays
reachable, so look at `free -m` and `sudo systemctl status 'benchboss-web@*'` before blaming
the network.

## Automatic deploys from GitHub

The repository has two workflows:

- **CI** ([ci.yml](../.github/workflows/ci.yml)) runs lint and tests on every push to `main`
  and on pull requests, on Linux, macOS and Windows.
- **Deploy** ([deploy.yml](../.github/workflows/deploy.yml)) runs when CI **passes on a push to
  `main`**, and installs that exact commit on the server. It also has a manual button.

The deploy job only ever runs one command on the server: `update.sh` with a full commit sha, a
version tag, or the words `rollback` and `status`. That is enforced on the server, not just in
the workflow (next section), so a leaked deploy key cannot open a shell.

It never runs for a pull request, including one from a fork, and two deploys never run at the
same time. After deploying it requests your sign in page from GitHub's servers and fails if it
does not answer.

### One-time setup

**1. Make a deploy key that can do one thing.** On your computer:

```bash
ssh-keygen -t ed25519 -N '' -C benchboss-ci -f ./ci-key
```

(No passphrase: it is used by a machine, and the restriction below is what protects it.)

**2. Allow it on the server, restricted to the updater.**

```bash
echo "command=\"/opt/benchboss/update.sh\",restrict $(cut -d' ' -f1,2 ci-key.pub) benchboss-ci" \
  | ssh -i ~/.ssh/benchboss_ssh bb@SERVER_IP 'cat >> ~/.ssh/authorized_keys'
```

`command=` makes every login with this key run the updater and nothing else, whatever the
client asks for. `restrict` turns off shells, port forwarding and the rest. Test it:

```bash
ssh -i ./ci-key -o IdentitiesOnly=yes bb@SERVER_IP status      # shows the releases
ssh -i ./ci-key -o IdentitiesOnly=yes bb@SERVER_IP 'ls /'      # refused
```

**3. Note the server's identity,** so GitHub cannot be tricked into deploying to another
machine:

```bash
ssh-keyscan -t ed25519 SERVER_IP 2>/dev/null                    # this line is DEPLOY_KNOWN_HOSTS
ssh -i ~/.ssh/benchboss_ssh bb@SERVER_IP 'ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub'
ssh-keyscan -t ed25519 SERVER_IP 2>/dev/null | ssh-keygen -lf -   # the two fingerprints must match
```

**4. Create the `production` environment on GitHub.** Repository, Settings, Environments, New
environment, named `production`. Under it:

- Deployment branches: only `main`.
- Required reviewers: add yourself if you want to approve each deploy (optional).
- Secrets: `DEPLOY_SSH_KEY` is the whole content of the `ci-key` file (`pbcopy < ci-key`), and
  `DEPLOY_KNOWN_HOSTS` is the line from step 3.
- Variables: `DEPLOY_HOST` is `bb@SERVER_IP`, and `DEPLOY_URL` is the public address, for
  example `https://203-0-113-7.sslip.io`.

**5. Delete the local copy of the key** and clear the clipboard:

```bash
rm ci-key ci-key.pub && pbcopy < /dev/null
```

**6. Merge to `main`.** GitHub runs a `workflow_run` workflow only from the default branch, so
the Deploy workflow starts working once it is on `main`.

### Using it

- **Normal flow:** merge to `main`. CI runs, then Deploy installs that commit. Watch it under
  the Actions tab.
- **Deploy a tag or an older commit:** Actions, Deploy, Run workflow, action `deploy`, and the
  full sha or tag in `ref`.
- **Roll back:** Actions, Deploy, Run workflow, action `rollback`. Or from your computer:
  `deploy/deploy.sh rollback bb@SERVER_IP`.
- **Turn automatic deploys off:** disable the Deploy workflow in the Actions tab. Manual
  `deploy/deploy.sh` still works.

### Keeping it simple on purpose

There is no staging server, no build artifact store and no database migration step. The server
downloads the commit from GitHub and builds it, which takes under a minute on a small server.
If you later want a staging copy, add a second server and a second environment with its own
secrets, and let the workflow deploy to it first. If the repository becomes private, the server
needs a read token to download (set `BENCHBOSS_REPO` and teach `update.sh` to send it), or the
workflow can send the source itself with `git archive`, like `deploy.sh --local` does.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `update: uv is not installed` | The server was not bootstrapped. Run `deploy/deploy.sh bootstrap`. |
| `update: that does not look like benchboss` | The download was empty or the ref does not exist on GitHub. A branch or commit that is only on your computer needs `--local`. |
| Update ends with `failed its check` | The new version did not start. Look in `/opt/benchboss/failed/` and the journal (above). The site stayed on the old version. |
| Caddy shows 502 | The web app behind it is down or restarting: `sudo systemctl status benchboss-web@NAME` and `sudo journalctl -u benchboss-web@NAME -n 50`. |
| The server stops answering SSH and the page | Out of memory. Power cycle from the provider's panel, then check `free -m`. Add swap (bootstrap does) or use a bigger server. |
| `benchboss-users add` says a port belongs to another user | Leave `--port` out and one is chosen. |
| Deploy job: `Permission denied (publickey)` | The key secret is incomplete (include the `BEGIN` and `END` lines) or the `authorized_keys` line has a typo. Test it by hand as in step 2. |
| Deploy job: `Host key verification failed` | `DEPLOY_KNOWN_HOSTS` does not match the server (for example after rebuilding it). Redo step 3. |
| Deploy job never starts after a merge | The Deploy file is not on `main` yet, or CI failed, or the environment waits for your approval. |
