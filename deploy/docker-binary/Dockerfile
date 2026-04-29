FROM ubuntu:24.04

WORKDIR /app

# Install certificates and unzip for the fully isolated native python updater
RUN apt-get update && apt-get install -y ca-certificates unzip && rm -rf /var/lib/apt/lists/*

# Execute the download sequence first, THEN start the bot with llamafile enabled
CMD ./SoulClone-Linux download --embedding --llamafile && ./SoulClone-Linux bot --llamafile