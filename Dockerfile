FROM python:3.10

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

COPY . /opt/src

WORKDIR /opt/src

RUN apt-get update && apt-get upgrade -y && apt-get install cmake -y && apt-get install build-essential -y

RUN pip install poetry

RUN poetry build

RUN pip install /opt/src/dist/*.whl

RUN apt-get purge build-essential -y && rm -rf /var/lib/apt/lists/* && rm -rf /opt/src

WORKDIR /opt/app

COPY main.py ./

CMD [ "python", "./main.py" ]
