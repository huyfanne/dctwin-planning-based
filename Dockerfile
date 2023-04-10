FROM python:3.9

WORKDIR /opt/app
COPY dist/dctwin-0.4.3-py3-none-any.whl ./
RUN pip install dctwin-0.4.3-py3-none-any.whl

COPY main.py ./

CMD [ "python", "./main.py" ]
