# Stage 1: Build contracts and extract ABIs
FROM oven/bun:1-slim AS contracts-builder

WORKDIR /contracts

# Copy dependency files first (for layer caching)
COPY contracts/package.json contracts/bun.lock ./
RUN bun install --frozen-lockfile

# Copy only files needed for compilation (no node_modules, artifacts, cache)
COPY contracts/hardhat.config.ts contracts/tsconfig.json ./
COPY contracts/contracts/ ./contracts/
COPY contracts/tasks/ ./tasks/
COPY contracts/utils/ ./utils/

# Compile contracts
RUN bun run hardhat compile

# Stage 2: Python runtime
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install Python dependencies
RUN uv sync --frozen

# Copy source code
COPY rofl_oracle/ ./rofl_oracle/

# Copy pre-compiled ABIs directly
COPY abis/ ./abis/

# Run the oracle using module execution
ENTRYPOINT ["uv", "run", "python", "-m", "rofl_oracle"]
