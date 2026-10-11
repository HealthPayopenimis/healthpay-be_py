FROM python:3.11-bookworm AS builder
ENV PYTHONUNBUFFERED 1
ARG DB_DEFAULT

# System dependencies
RUN apt-get update && apt-get install -y \
    apt-transport-https \
    ca-certificates \
    gettext \
    unixodbc-dev \
    python3-dev \
    git \
    jq \
    && apt-get upgrade -y

# MSSQL client (optional, depending on DB_DEFAULT)
RUN test "$DB_DEFAULT" != "postgresql" && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - || :
RUN test "$DB_DEFAULT" != "postgresql" && curl https://packages.microsoft.com/config/debian/10/prod.list > /etc/apt/sources.list.d/mssql-release.list || :
RUN test "$DB_DEFAULT" != "postgresql" && apt-get update || :
RUN test "$DB_DEFAULT" != "postgresql" && ACCEPT_EULA=Y apt-get install -y msodbcsql17 mssql-tools18 || :

# Python requirements
RUN pip install --upgrade pip
RUN pip install gunicorn

# Stage: App
FROM builder AS base


# Copy app source
RUN mkdir /openimis-be
COPY . /openimis-be
WORKDIR /openimis-be
RUN chmod a+x /openimis-be/script/entrypoint.sh /openimis-be/script/load_fixture.sh

# Install requirements
# Preserve the corrected V2 dependency baseline for this bounded QA change.
ENV PIP_CONSTRAINT=/openimis-be/constraints-v3-qa.txt
RUN pip install -r requirements.txt
RUN pip install -r sentry-requirements.txt

# Environment for module parsing
ARG OPENIMIS_CONF_JSON
ENV OPENIMIS_CONF_JSON ${OPENIMIS_CONF_JSON}

# Install module-specific requirements
WORKDIR /openimis-be/script

FROM base AS dev
# Development stage - modules installed at runtime with caching

# Entrypoint
ENTRYPOINT ["/bin/bash", "/openimis-be/script/entrypoint.sh"]

FROM base AS prod
# Production stage - pre-install modules during build
WORKDIR /openimis-be/script
COPY ./openimis.json /openimis-be/openimis.json
RUN python modules-requirements.py ../openimis.json > modules-requirements.txt && \
    pip install -r modules-requirements.txt

FROM base AS app
# Legacy stage for backward compatibility - includes everything

# COPY the solution fixture
COPY ./fixtures /openimis-be/fixtures

# COPY the openimis,json from soltuions
COPY ./openimis.json /openimis-be/openimis.json

RUN python modules-requirements.py ../openimis.json > modules-requirements.txt && pip install -r modules-requirements.txt

# Collect static assets and messages
WORKDIR /openimis-be/openIMIS
RUN NO_DATABASE=True python manage.py compilemessages -x zh_Hans --locale en
RUN NO_DATABASE=True python manage.py collectstatic --clear --noinput

# Entrypoint
ENTRYPOINT ["/bin/bash", "/openimis-be/script/entrypoint.sh"]
