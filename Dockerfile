FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

RUN pip install poetry
COPY . /opt/src
WORKDIR /opt/src
RUN poetry build

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

COPY --from=builder /opt/src/dist/*.whl /opt/dist/
RUN --mount=type=secret,id=GITHUB_TOKEN \
    GITHUB_TOKEN=$(cat /run/secrets/GITHUB_TOKEN)  && echo "https://x-access-token:${GITHUB_TOKEN}@github.com" > ${HOME}/.git-credentials && \
    apt-get update && apt-get upgrade -y && \
    apt-get install -y git cmake build-essential pigz libglx-mesa0 && \
    git config --global credential.helper store && \
    pip install --no-cache-dir /opt/dist/*.whl && \
    apt-get update && apt-get upgrade -y && \
    apt-get install cmake build-essential pigz libglx-mesa0 -y && \
    apt-get purge build-essential cmake -y && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* && \
    rm -rf ${HOME}/.git-credentials && \
    rm -rf /root/.cache/pip/* && \
    find /usr/local/lib/python*/site-packages -name "*.pyc" -delete && \
    find /usr/local/lib/python*/site-packages -name "__pycache__" -type d -exec rm -rf {} +

WORKDIR /opt/app

COPY ./run/cfd.py ./
COPY ./run/eplus.py ./
COPY ./run/eplus_cfd_cosim.py ./

CMD [ "python", "./cfd.py" ]
