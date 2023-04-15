FROM python:3.10

WORKDIR /opt/app
COPY dist/ ./
RUN pip install *
COPY main.py ./

CMD [ "python", "./main.py" ]
