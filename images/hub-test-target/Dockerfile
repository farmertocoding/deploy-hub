# hub-test-target — D-015 T2 image.
# Ubuntu + systemd PID 1 + sshd + docker (vfs) + Caddy.
# Locally built (or multi-arch). Runtime: --privileged --cgroupns=host.
FROM ubuntu:22.04

ENV container=docker \
    DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8

# Refuse service starts during build (no PID 1 yet).
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod +x /usr/sbin/policy-rc.d

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        systemd \
        systemd-sysv \
        dbus \
        openssh-server \
        sudo \
        ca-certificates \
        curl \
        iptables \
    && apt-get install -y docker.io \
    && rm -rf /var/lib/apt/lists/*

# Caddy binary (both amd64 and arm64). Package repos are not assumed.
ARG CADDY_VERSION=2.8.4
RUN arch="$(dpkg --print-architecture)" \
    && curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${arch}.tar.gz" \
        | tar -xz -C /usr/local/bin caddy \
    && chmod +x /usr/local/bin/caddy \
    && mkdir -p /etc/caddy

COPY 99-hub-hardening.conf /etc/ssh/sshd_config.d/99-hub-hardening.conf
COPY daemon.json /etc/docker/daemon.json
COPY Caddyfile /etc/caddy/Caddyfile
COPY caddy.service /etc/systemd/system/caddy.service

RUN mkdir -p /etc/ssh/sshd_config.d \
    && useradd --create-home --shell /bin/bash --groups sudo,docker deploy \
    && printf 'deploy ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/deploy \
    && chmod 440 /etc/sudoers.d/deploy \
    && mkdir -p /home/deploy/.ssh \
    && chmod 700 /home/deploy/.ssh \
    && chown -R deploy:deploy /home/deploy/.ssh \
    && systemctl mask console-getty.service getty@tty1.service \
    && systemctl enable ssh docker caddy \
    && rm -f /usr/sbin/policy-rc.d

STOPSIGNAL SIGRTMIN+3
CMD ["/lib/systemd/systemd"]
