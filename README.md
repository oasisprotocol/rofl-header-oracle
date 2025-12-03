# ROFL Header Oracle

A Python-based Oasis ROFL (Runtime OFf-chain Logic) oracle that fetches block
headers from source chains and submits them to the ROFLAdapter contract on
Oasis Sapphire for cross-chain bridge verification.

## Overview

This oracle listens for `BlockHeaderRequested` events from a source chain
contract and responds by fetching the requested block headers and submitting
them to the Oasis Sapphire network through the ROFL runtime. It's designed to
work as part of a Hashi-based cross-chain bridge system.

## Architecture

- **Source Chain**: Listens for events on any EVM-compatible blockchain
- **Target Chain**: Submits block headers to Oasis Sapphire via ROFL
- **ROFL Runtime**: Uses Oasis confidential compute for secure oracle operations
- **Event-Driven**: Processes `BlockHeaderRequested` events in real-time

## Requirements

- Docker and Docker Compose
- Access to a ROFL-enabled Oasis Network environment
- Source chain RPC endpoint
- Deployed contracts:
  - `BlockHeaderRequester` on source chain
  - `ROFLAdapter` on Oasis Sapphire

## Configuration

The oracle is configured through environment variables defined in `compose.yaml`:

### Environment Variables

The oracle supports three modes: **event_listener**, **push**, and
**watcher**. Some environment variables are required for all modes, while
others are specific to a mode.

#### **Common Variables (All Modes)**

| Variable               | Description                                               | Default                              | Required |
|------------------------|----------------------------------------------------------|--------------------------------------|----------|
| `PYTHONUNBUFFERED`     | Disable Python output buffering for immediate logs       | `1`                                  | No       |
| `SOURCE_RPC_URL`       | RPC endpoint for the source chain                        | `https://ethereum.publicnode.com`    | No       |
| `TARGET_RPC_URL`       | RPC endpoint for the target chain                        | `https://testnet.sapphire.oasis.io`  | No       |
| `ROFL_ADAPTER_ADDRESS` | Address of the ROFLAdapter contract on Oasis Sapphire    | -                                    | **Yes**  |
| `REQUEST_TIMEOUT`      | HTTP request timeout (seconds)                           | `30`                                 | No       |
| `RETRY_COUNT`          | Number of retry attempts for operations                  | `3`                                  | No       |
| `ORACLE_MODE`          | Operating mode: `event_listener`, `push`, or `watcher`   | `event_listener`                     | No       |
| `LOG_LEVEL`            | Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL     | `INFO`                               | No       |
| `JSON_LOGS`            | Enable JSON-formatted structured logging                 | `false`                              | No       |

---

#### **Event Listener Mode (`ORACLE_MODE=event_listener`)**

| Variable                   | Description                                                        | Default | Required |
|----------------------------|--------------------------------------------------------------------|---------|----------|
| `SOURCE_CONTRACT_ADDRESS`  | Address of the BlockHeaderRequester contract on source chain       | -       | **Yes**  |
| `POLLING_INTERVAL`         | Seconds between event checks                                       | `12`    | No       |
| `LOOKBACK_BLOCKS`          | Number of blocks to look back on startup                           | `100`   | No       |

---

#### **Push Mode (`ORACLE_MODE=push`)**

| Variable           | Description                                   | Default | Required |
|--------------------|-----------------------------------------------|---------|----------|
| `PUSH_INTERVAL`    | Seconds between block pushes                  | `60`    | No       |
| `PUSH_BATCH_SIZE`  | Max blocks to push per iteration              | `20`    | No       |

---

#### **Watcher Mode (`ORACLE_MODE=watcher`)**

| Variable                        | Description                                         | Default | Required |
|---------------------------------|-----------------------------------------------------|---------|----------|
| `WATCH_ADDRESSES`               | Comma-separated list of addresses to watch          | -       | **Yes**  |
| `SCAN_INTERVAL`                 | Seconds between scanning for interactions           | `60`    | No       |
| `WATCHER_BATCH_SIZE`            | Max blocks to scan per iteration                    | `50`    | No       |
| `LOOKBACK_BLOCKS`               | Number of blocks to look back on startup            | `100`   | No       |
| `ENABLE_INTERNAL_TX_DETECTION`  | Enable internal transaction detection               | `false` | No       |

**Internal Transaction Detection:**

When `ENABLE_INTERNAL_TX_DETECTION=true`, the watcher will also detect interactions
that occur via internal transactions (contract-to-contract calls). This feature:

- **Requires:** Archive node with `debug_traceTransaction` API support
- **Performance:** Significantly slower due to tracing overhead (trace each
  transaction)
- **Use case:** Critical when watched addresses primarily interact via smart
  contracts
- **Recommended:** Only enable if you have access to archive nodes and need
  comprehensive tracking

Without this feature, only direct (external) transactions to/from watched
addresses are detected.

---

#### **Local Mode (Testing Only)**

| Variable            | Description                                | Default | Required           |
|---------------------|--------------------------------------------|---------|--------------------|
| `LOCAL_PRIVATE_KEY` | Private key for local testing mode         | -       | **Yes (Local Mode)** |

---

**Note:**

- All addresses must be valid EVM addresses (checksummed).
- `LOCAL_PRIVATE_KEY` is only required for local mode/testing.
- If a required variable is missing for the selected mode, the oracle will
  fail to start with a clear error.

---

#### Important Notes

- **`PYTHONUNBUFFERED=1`**: Essential for real-time log visibility in
containerized environments. Without this, log output may be buffered and not
appear immediately, making the oracle appear "stuck" when it's actually running normally.
- **`LOCAL_PRIVATE_KEY`**: Required only when running in local mode for testing
without ROFL utilities. Should be a hex-encoded private key.
- **`ENABLE_INTERNAL_TX_DETECTION`**: When enabled in watcher mode, uses
`debug_traceTransaction` to detect internal contract calls. This requires:
  - Archive node access (full nodes won't work)
  - Debug API enabled on the RPC endpoint
  - May require premium RPC provider plans
  - Significantly increases processing time (10-100x slower)
  - Only use if absolutely necessary for your use case

## Usage

### 1. Set Environment Variables

Create a `.env` file or set environment variables:

```bash
# Required for all modes
export ROFL_ADAPTER_ADDRESS=0xYourROFLAdapterAddress
export SOURCE_RPC_URL=https://your-source-chain-rpc.com
export ORACLE_MODE=event_listener

# Required for event_listener mode
export SOURCE_CONTRACT_ADDRESS=0xYourBlockHeaderRequesterAddress

# Optional: configure other settings
export POLLING_INTERVAL=12
export LOOKBACK_BLOCKS=100
```

### 2. Run with Docker Compose

```bash
docker-compose up --build
```

### 3. Monitor Logs

The oracle will display:

- Initialization progress
- ROFL connection status
- Block range being monitored
- Event processing status
- Periodic heartbeat messages

## Local Mode (Testing)

For testing and development without ROFL infrastructure, the oracle supports a
local mode that simulates transaction submissions and skips ROFL utilities.

### Local Mode Features

- **No ROFL Dependencies**: Skips ROFL utility initialization and socket connections
- **Transaction Simulation**: Logs transaction details instead of actual submission
- **Event Listening**: Full WebSocket and polling event listening functionality
- **Local Private Key**: Uses a local private key for contract interaction testing

### Running in Local Mode

Use the dedicated local testing Docker Compose configuration:

```bash
# Run with local testing configuration
docker compose -f compose.local.yaml up --build
```

### Local Mode Environment Variables

In addition to the standard variables, local mode requires:

```bash
# Required for local mode - add this to your .env file
LOCAL_PRIVATE_KEY=0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef
```

## Operation

1. **Initialization**: Connects to ROFL runtime and source chain
2. **Event Monitoring**: Polls for `BlockHeaderRequested` events
3. **Block Fetching**: Retrieves requested block headers from source chain
4. **Header Submission**: Submits headers to Sapphire via ROFL
5. **Continuous Operation**: Runs in an infinite loop with configurable intervals

## Monitoring & Health Checks

The oracle includes built-in health check endpoints for container orchestration
and monitoring:

### Health Endpoints

- **`/health`** - Overall system health with component status
- **`/health/live`** - Liveness probe (is the service running)
- **`/health/ready`** - Readiness probe (is the service ready to handle work)

Health endpoints are exposed on port 8080 by default.

### Example Health Check

```bash
# Check overall health
curl http://localhost:8080/health

# Liveness probe (for Kubernetes/Docker)
curl http://localhost:8080/health/live

# Readiness probe
curl http://localhost:8080/health/ready
```

### Error Handling & Resilience

The oracle includes production-grade error handling:

- **Exponential Backoff**: Automatic retry with exponential backoff for
  transient failures
- **Circuit Breakers**: Prevents cascading failures when RPCs are down
- **Retry Logic**: Configurable retry attempts (via `RETRY_COUNT`) for all
  critical operations
- **Graceful Degradation**: Continues operating even with degraded connectivity

### Structured Logging

Enable JSON-formatted structured logging for production environments:

```bash
export JSON_LOGS=true
```

This outputs logs in JSON format for easier parsing by log aggregation systems
(ELK, Splunk, DataDog, etc.).

## Development

### Dependencies

- Python 3.10+
- oasis-sapphire-py
- web3.py
- httpx
- cbor2
- aiohttp

### Local Development

```bash
# Install dependencies
make sync

# Run tests
make test

# Run tests with coverage
make test-cov

# Format code
make format

# Lint code
make lint

# Fix linting issues
make lint-fix

# Run all checks (format, lint, test)
make pre-commit

# Run the application (via Docker Compose)
docker compose -f compose.local.yaml up --build
```

## Architecture Integration

This oracle is designed to work with:

- Hashi cross-chain message verification system
- Oasis ROFL confidential compute runtime
- EVM-compatible source chains
