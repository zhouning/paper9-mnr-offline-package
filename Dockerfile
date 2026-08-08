ARG BASE_IMAGE=python:3.11-bookworm
FROM ${BASE_IMAGE}

ARG TARGETPLATFORM
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG PACKAGE_VERSION=0.4.0
ARG ALGORITHM_NAME=paper9v2
ARG ALGORITHM_VERSION=2.3.0
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG LEGACY_X86_64=0
ARG LEGACY_CONSTRAINTS=constraints/legacy-x86_64.txt
ARG REUSE_INSTALLED_DEPS=0

LABEL org.opencontainers.image.title="Paper9 MNR offline package" \
      org.opencontainers.image.version="${PACKAGE_VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_TIME}" \
      org.opencontainers.image.source="https://github.com/zhouning/paper9-mnr-offline-package" \
      io.paper9.algorithm.name="${ALGORITHM_NAME}" \
      io.paper9.algorithm.version="${ALGORITHM_VERSION}" \
      io.paper9.input.profile="dltb_dem_only"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PAPER9_OFFLINE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg

WORKDIR /app

COPY pyproject.toml README.md environment.yml ./
COPY src ./src
COPY constraints ./constraints

RUN if [ "${REUSE_INSTALLED_DEPS}" = "1" ]; then \
         python -m pip install --no-build-isolation --no-deps .[dev,notebook]; \
       else \
         python -m pip install --upgrade pip setuptools wheel \
         && if [ "${LEGACY_X86_64}" = "1" ]; then \
         python -m pip install --extra-index-url "${PIP_EXTRA_INDEX_URL}" -c constraints/legacy-x86_64.txt -r "${LEGACY_CONSTRAINTS}" \
         && python -m pip install --no-deps .[dev,notebook]; \
         else \
           python -m pip install --extra-index-url "${PIP_EXTRA_INDEX_URL}" ".[dev,notebook]"; \
         fi; \
       fi

COPY Dockerfile ./
COPY scripts ./scripts
COPY configs ./configs
COPY deploy ./deploy
COPY docs ./docs
COPY notebooks ./notebooks
COPY reference ./reference
COPY tests ./tests
COPY wheelhouse ./wheelhouse

RUN python scripts/00_check_env.py --include-notebook \
    && if [ "${LEGACY_X86_64}" = "1" ]; then \
         python scripts/check_legacy_cpu_compat.py --require-legacy-amd64; \
       fi

CMD ["paper9-mnr", "--help"]
