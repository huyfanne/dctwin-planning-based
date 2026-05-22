FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

RUN pip install --no-cache-dir poetry && \
    poetry --version

COPY . /opt/src
WORKDIR /opt/src
RUN poetry build && \
    pip uninstall -y poetry && \
    rm -rf /root/.cache/pip/* && \
    rm -rf /root/.cache/pypoetry/* && \
    (find /opt/src -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
     find /opt/src -type f -name "*.pyc" -delete 2>/dev/null; \
     exit 0)


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

COPY --from=builder /opt/src/dist/*.whl /opt/dist/
RUN --mount=type=secret,id=GITHUB_TOKEN \
    GITHUB_TOKEN=$(cat /run/secrets/GITHUB_TOKEN) && \
    echo "https://x-access-token:${GITHUB_TOKEN}@github.com" > ${HOME}/.git-credentials && \
    apt-get update && \
    apt-get install -y --no-install-recommends git cmake build-essential pigz libglx-mesa0 && \
    git config --global credential.helper store && \
    pip install --no-cache-dir /opt/dist/*.whl && \
    pip uninstall -y wheel && \
    apt-get purge -y build-essential cmake git && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* ${HOME}/.git-credentials /root/.cache/pip/* && \
    (find /usr/local/lib/python*/site-packages -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null; \
     find /usr/local/lib/python*/site-packages -type d -name "tests" -exec rm -rf {} + 2>/dev/null; \
     find /usr/local/lib/python*/site-packages -type d -name "test" -exec rm -rf {} + 2>/dev/null; \
     find /usr/local/lib/python*/site-packages -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
     find /usr/local/lib/python*/site-packages -type f -name "*.pyc" -delete 2>/dev/null; \
     find /usr/local/lib/python*/site-packages -type f -name "*.pyo" -delete 2>/dev/null; \
     find /usr/local/lib/python*/site-packages -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null; \
     exit 0)

WORKDIR /opt/app

COPY ./run/cfd.py ./
COPY ./run/eplus.py ./
COPY ./run/eplus_cfd_cosim.py ./

CMD ["python", "./cfd.py"]
