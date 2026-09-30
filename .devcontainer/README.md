# Combined development container

Open `firmware-dev` in VS Code and select **Dev Containers: Reopen in Container**.
The image uses Debian 13.6 and runs as a copy of the host user: same username,
UID/GID (`1000:1000`), and home path (`$HOME`, e.g. `/var/home/tom`), passed in
as build args from `devcontainer.json`. UID rewriting is disabled. If your
UID/GID are not 1000, edit `USER_UID`/`USER_GID` in `devcontainer.json`. CMake 3.x supports both projects, including the firmware's older
CMake minimum version.

The setup includes the AArch64 Linux and bare-metal ARM toolchains, native GDB,
GDB multiarch, OpenOCD, Clang, both projects' build dependencies, and R.
The C++, GitHub pull request, and Claude Code extensions are installed.

## Claude Code

Claude Code is installed with the native installer (as on the host); run
`claude` in the terminal. The user-level Claude state is shared live with the
host, not copied: host `~/.claude` and `~/.claude.json` are bind-mounted at the
same paths. Settings, memories, sessions, plugins, skills, and the login are
therefore identical in both places. Because the home path and workspace path
match the host, absolute paths stored in `~/.claude` (plugin and marketplace
locations, hooks, `~/.claude/projects/<path>` session and memory directories)
resolve unchanged, and this workspace picks up its existing sessions and memory.
`initializeCommand` creates `~/.claude` and `~/.claude.json` on the host first so
Docker does not create them as root. `jq` is installed for the status-line
command in `~/.claude/settings.json`.

Host and container sessions write the same files concurrently (history,
sessions, `~/.claude.json`); avoid running both on the same project at once.
Hooks or status-line commands that call host-only tools will fail in the
container until those tools are added to the image.

## Codex

Codex CLI is installed when the image builds; run `codex` in the terminal. Host
`~/.config/codex` is mounted at `~/.codex`, as in the existing repository setups.
Separate Docker volumes cover `packages`, `app-server-control`, and
`app-server-daemon` inside that mount. Host packages contain absolute symlinks
that point into `~/.config/codex`, which the container sees as `~/.codex`; daemon sockets, updater
locks, and process state also belong to the container. `volume-nocopy` prevents
importing those host files into new volumes.
The container's `postStartCommand` makes the volume roots writable by the
container user, then installs the matching daemon if missing and starts it.
Configuration and login remain shared with the host. Rebuild the devcontainer
after changing these mounts, the build args, or the Dockerfile.

## Wombat SSH access

The container reaches a Wombat on the LAN (`wombat-5051.lan`, user `kipr`) using
the host's SSH agent, which VS Code forwards into the container
(`SSH_AUTH_SOCK`). No host `~/.ssh` is mounted and no private key lives in the
container, so access only works while VS Code is attached. `ssh-add -l` inside
the container should list the host's keys.

`~/.ssh/config` is container-local and is lost when the container is rebuilt.
Re-create it with:

```sh
mkdir -p ~/.ssh && cat > ~/.ssh/config <<'EOF'
Host wombat
  HostName wombat-5051.lan
  User kipr
  BatchMode yes
  ConnectTimeout 10
  ServerAliveInterval 15
  ServerAliveCountMax 4
  ControlMaster auto
  ControlPath ~/.ssh/cm-%C
  ControlPersist 4h
EOF
chmod 600 ~/.ssh/config
```

`ControlMaster` keeps one connection open for 4 hours, so repeated `ssh`/`scp`
calls are fast and do not re-authenticate. Check with `ssh -O check wombat`;
restart a stale one with `ssh -O exit wombat`. Change `HostName` if the Wombat
is a different unit or its `.lan` name does not resolve.

Verify with `ssh wombat hostname`. A `No route to host` or timeout means the
Wombat is off or off the network (check from the host first), not a container
problem. The container's default bridge network can reach the LAN.

Claude Code permissions live in the host-shared `~/.claude/settings.json`, so
they survive rebuilds. They allow `ssh wombat`, `scp`, and `rsync` without
prompts:

```json
"permissions": { "allow": [
  "Bash(ssh wombat:*)", "Bash(ssh -O check wombat)",
  "Bash(scp:*)", "Bash(rsync:*)"
] }
```

The Wombat (Debian, aarch64) has `rsync`, `gdb`, `gdbserver` (installed with
`sudo apt-get install gdbserver`; the `kipr` user has passwordless sudo), and
`python3`. The container image includes `openssh-client` and `rsync`.

## Workspace

The workspace is mounted at its host path. An additional mount exposes the
sibling `../libwallaby` checkout at its host path so this workspace's absolute
`libwallaby` symlink resolves inside the container. Keep that sibling checkout
when using this configuration.

Run the documented native builds in the container's Bash shell:

```sh
bash
cd libwallaby
cmake -Bbuild -DCMAKE_TOOLCHAIN_FILE=toolchain/aarch64-linux-gnu.cmake .
cmake --build build -j "$(nproc)"
cd ../Wombat-Firmware
./build.sh
```

Use clean build directories when switching environments: CMake caches absolute
paths and toolchain selections. The older libwallaby `README.md` names the
32-bit toolchain; `2README2FURIOUS.md` documents the current AArch64 build above.
The firmware's `AGENTS.md` documents `./build.sh` for an installed toolchain.
Docker-in-Docker is not required.

From the workspace root, run the analysis with:

```sh
Rscript Wombat-Firmware-data/gyro_stats.R \
    Wombat-Firmware-data/gyro_pre.csv Wombat-Firmware-data/gyro_post.csv
```

The script needs only base R. GDB attachment is enabled with `SYS_PTRACE` and
an unrestricted seccomp profile. For remote debugging, use `gdb-multiarch` for
both ARM targets; USB probes need an appropriate host device mount before
OpenOCD can access them.

Build the image independently of VS Code from the workspace root:

```sh
docker build -t wombat-combined-dev \
    --build-arg USERNAME="$USER" --build-arg USER_HOME="$HOME" \
    --build-arg USER_UID="$(id -u)" --build-arg USER_GID="$(id -g)" \
    .devcontainer
```

Without the build args the image falls back to a `code` user at `/home/code`,
where absolute paths in a mounted `~/.claude` would not resolve.
