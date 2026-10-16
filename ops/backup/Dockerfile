FROM postgres:16-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends restic ca-certificates util-linux && rm -rf /var/lib/apt/lists/*
COPY backup.sh /backup.sh
RUN chmod 755 /backup.sh
ENTRYPOINT ["/backup.sh"]
CMD []
