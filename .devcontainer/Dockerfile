FROM debian:13.6

ENV TZ=America/Chicago

# libpython3.13-dev supplies ARM headers/libraries without an ARM interpreter,
# which would conflict with the native Python required by development tools.
RUN dpkg --add-architecture arm64 \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        binutils \
        build-essential \
        ca-certificates \
        clang \
        cmake \
        curl \
        doxygen \
        fd-find \
        file \
        fish \
        fzf \
        g++-aarch64-linux-gnu \
        gcc-aarch64-linux-gnu \
        gcc-arm-none-eabi \
        gdb \
        gdb-multiarch \
        gh \
        git \
        gnupg \
        jq \
        libnewlib-arm-none-eabi \
        libpython3.13-dev:arm64 \
        libx11-dev:arm64 \
        nodejs \
        npm \
        openocd \
        openssh-client \
        python3 \
        r-base \
        ripgrep \
        rsync \
        sudo \
        swig \
        tzdata \
        unzip \
        wget \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex \
    && npm cache clean --force \
    && codex --version

# The container user mirrors the host user's name, IDs, and home path so that
# absolute paths stored in the bind-mounted ~/.claude (plugin install
# locations, marketplaces, hooks, per-project session and memory directories)
# resolve identically inside the container. The defaults suit standalone builds.
ARG USERNAME=code
ARG USER_UID=1000
ARG USER_GID=1000
ARG USER_HOME=/home/code

RUN groupadd --gid "$USER_GID" "$USERNAME" \
    && mkdir -p "$(dirname "$USER_HOME")" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" --home-dir "$USER_HOME" \
        --create-home --shell /usr/bin/fish "$USERNAME" \
    && printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$USERNAME" > "/etc/sudoers.d/$USERNAME" \
    && chmod 0440 "/etc/sudoers.d/$USERNAME"

USER $USER_UID:$USER_GID
WORKDIR $USER_HOME

# Claude Code native installer, matching the host installation. The binary
# lives in ~/.local inside the image; only ~/.claude and ~/.claude.json are
# shared with the host.
ENV PATH="$USER_HOME/.local/bin:$PATH"
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && claude --version

CMD ["fish"]
