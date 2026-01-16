FROM python:3.10-slim as builder

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

RUN pip install poetry
COPY . /opt/src
WORKDIR /opt/src
RUN poetry build

FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

COPY --from=builder /opt/src/dist/*.whl /opt/dist/
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y git cmake build-essential pigz libglx-mesa0 && \
    echo "https://x-access-token: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@github.com" > ${HOME}/.git-credentials && \
    git config --global credential.helper store && \
    pip install --no-cache-dir /opt/dist/*.whl && \
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
