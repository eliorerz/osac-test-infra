FROM registry.access.redhat.com/ubi9/ubi:latest

ARG GRPCURL_VERSION=1.9.1
ARG OSAC_CLI_VERSION=0.0.56

RUN dnf install -y python3.11 python3.11-pip make && dnf clean all

RUN curl -Lsf "https://mirror.openshift.com/pub/openshift-v4/x86_64/clients/ocp/stable/openshift-client-linux.tar.gz" \
    | tar xz --no-same-owner -C /usr/local/bin oc kubectl

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN curl -Lsf "https://github.com/fullstorydev/grpcurl/releases/download/v${GRPCURL_VERSION}/grpcurl_${GRPCURL_VERSION}_linux_x86_64.tar.gz" \
    | tar xz --no-same-owner -C /usr/local/bin grpcurl

RUN curl -Lsfo /usr/local/bin/osac "https://github.com/osac-project/fulfillment-service/releases/download/v${OSAC_CLI_VERSION}/osac_Linux_x86_64" \
    && chmod +x /usr/local/bin/osac

WORKDIR /tests

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --python python3.11

COPY . .

ENV PATH="/tests/.venv/bin:$PATH"
