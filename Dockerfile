FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
  gdal-bin postgresql-14-postgis-3 python3-pip \
  && rm -rf /var/lib/apt/lists/*

RUN /etc/init.d/postgresql start \
  && su postgres -c 'createdb edge_extender' \
  && su postgres -c 'psql -d edge_extender -c "CREATE EXTENSION postgis;"'

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

COPY processing ./processing

CMD /etc/init.d/postgresql start && su postgres -c 'python3 -m processing'
