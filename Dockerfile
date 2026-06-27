ARG BASE_IMAGE=python:3.11-bookworm
FROM ${BASE_IMAGE}

ARG TARGETPLATFORM
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG PACKAGE_VERSION=0.2.0
ARG ALGORITHM_NAME=paper9v2
ARG ALGORITHM_VERSION=2.0.0
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown

LABEL org.opencontainers.image.title="Paper9 MNR offline package" \
      org.opencontainers.image.version="${PACKAGE_VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.source="https://github.com/paper9/paper9-mnr-offline-package" \
      io.paper9.algorithm.name="${ALGORITHM_NAME}" \
      io.paper9.algorithm.version="${ALGORITHM_VERSION}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg

WORKDIR /app

COPY pyproject.toml README.md environment.yml ./
COPY src ./src

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --extra-index-url "${PIP_EXTRA_INDEX_URL}" ".[dev,notebook]"

COPY Dockerfile ./
COPY scripts ./scripts
COPY configs ./configs
COPY deploy ./deploy
COPY docs ./docs
COPY notebooks ./notebooks
COPY tests ./tests
COPY wheelhouse ./wheelhouse

RUN python scripts/00_check_env.py --no-heavy --include-notebook

CMD ["paper9-mnr", "--help"]
