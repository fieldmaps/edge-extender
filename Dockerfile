FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
  gnupg \
  && rm -rf /var/lib/apt/lists/*

RUN apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 6B827C12C2D425E227EDCA75089EBE08314DF160 \
  && echo "deb http://ppa.launchpad.net/ubuntugis/ubuntugis-unstable/ubuntu focal main" | tee /etc/apt/sources.list.d/ubuntugis.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
  gdal-bin postgresql-12-postgis-3 python3-pip \
  && rm -rf /var/lib/apt/lists/*

RUN /etc/init.d/postgresql start \
  && su postgres -c 'createdb polygon_voronoi' \
  && su postgres -c 'psql -d polygon_voronoi -c "CREATE EXTENSION postgis;"'

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

COPY config.ini ./config.ini
COPY processing ./processing

CMD /etc/init.d/postgresql start && su postgres -c 'python3 -m processing'
