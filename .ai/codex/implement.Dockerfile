FROM ghcr.io/openai/codex:0.144.6
USER 10001:10001
WORKDIR /workspace
ENTRYPOINT ["codex"]
