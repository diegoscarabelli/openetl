# syntax=docker/dockerfile:1

# 1. Use the specific Airflow version
FROM apache/airflow:3.1.0

# 2. Set USER airflow for initial steps that don't require root
USER airflow

# 3. Install Python requirements (as airflow user)
#    Ensure requirements.txt contains 'apache-airflow-providers-fab'
#    if you intend to use FabAuthManager or its CLI commands.
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# 4. Switch to root ONLY when needed (for apt-get installs)
USER root

# 5. Combine apt-get installs tools & cleanup
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gosu \
        iproute2 \
        iputils-ping \
        procps \
        sshpass \

    # Cleanup apt cache to reduce image size
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 6. Switch back to the default airflow user for runtime
USER airflow

# Any CMD or ENTRYPOINT from the base image will be inherited unless overridden here
