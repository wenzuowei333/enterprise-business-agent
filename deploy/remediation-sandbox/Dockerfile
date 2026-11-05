ARG BASE_IMAGE
FROM ${BASE_IMAGE}

USER root
RUN apk add --no-cache bash curl python3 coreutils postgresql16 postgresql16-client \
    && install -d -m 1777 /sandbox /tmp/pgdata /tmp/pgsocket
RUN rm -rf /tmp/pgdata /tmp/pgsocket
COPY remediation-sandbox /usr/local/bin/remediation-sandbox
RUN chmod 0555 /usr/local/bin/remediation-sandbox

USER 65534:65534
WORKDIR /sandbox
CMD ["/usr/local/bin/remediation-sandbox"]
