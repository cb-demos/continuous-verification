FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY . .

# Install dependencies
RUN uv sync --frozen --no-dev

# Run as non-root user for security
RUN useradd -m -u 1000 cvuser && chown -R cvuser:cvuser /app
USER cvuser

# Use the installed package directly from venv
ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["cv"]
CMD ["--help"]
