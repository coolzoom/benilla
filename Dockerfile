FROM rust:1.98-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential pkg-config libasound2-dev libudev-dev python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . .

# Keep the image's build reproducible and make the default container action the same
# offline test command used by local development after dependencies are cached.
RUN cargo fetch --locked
CMD ["make", "test"]
