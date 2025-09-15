FROM python:3.10 as builder

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

RUN pip install poetry
COPY . /opt/src
WORKDIR /opt/src
RUN poetry build

FROM python:3.10

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

COPY --from=builder /opt/src/dist/*.whl /opt/dist/
RUN echo "https://x-access-token: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@github.com" > ${HOME}/.git-credentials && \
    git config --global credential.helper store && \
    apt-get update && apt-get upgrade -y && \
    apt-get install cmake build-essential pigz libglx-mesa0 -y && \
    pip install /opt/dist/*.whl && \
    apt-get purge build-essential cmake -y && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf ${HOME}/.git-credentials

WORKDIR /opt/app

COPY ./run/cfd.py ./
COPY ./run/eplus.py ./
COPY ./run/eplus_cfd_cosim.py ./

CMD [ "python", "./cfd.py" ]
