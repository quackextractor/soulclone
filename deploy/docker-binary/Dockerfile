FROM ubuntu:24.04

WORKDIR /app

# Install certificates and aria2 for secure, parallel downloads during the ;update command
RUN apt-get update && apt-get install -y ca-certificates unzip aria2 && rm -rf /var/lib/apt/lists/*

# Execute the compiled binary
CMD ["./SoulClone-Linux", "bot"]