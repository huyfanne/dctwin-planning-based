FROM python:3.10

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

WORKDIR /opt/app
COPY ./dist /dist
RUN apt-get update && apt-get upgrade -y && apt-get install cmake -y && apt-get install build-essential -y && \
    pip install /dist/*.whl && \
    apt-get purge build-essential -y && rm -rf /var/lib/apt/lists/* && rm -rf /dist

COPY main.py ./

CMD [ "python", "./main.py" ]
