#!/usr/bin/bash

# ======================================================================================
# DOCKER ENGINE INSTALLATION SCRIPT
# ======================================================================================
# Description: This script installs Docker Engine and Docker Compose on Ubuntu/Debian
#              Linux systems using the official Docker APT repository. It configures
#              the system to allow running Docker commands without sudo.
#
# Platform Compatibility:
#   - Ubuntu/Debian Linux only.
#   - NOT compatible with macOS (Mac users should install Docker Desktop instead).
#
# Usage:
#   bash docker_install.sh
#
# Post-Installation:
#   - You must log out and log back in for docker group membership to take effect
#   - After logging back in, you can run docker commands without sudo
#   - Verify installation with: docker run hello-world
# ======================================================================================

# Create installation log file.
touch docker_installation.log
echo -e "Docker Installation Log\n" >> docker_installation.log
date  >> docker_installation.log

# Capture logging to file.
# Save file descriptors so they can be restored to whatever they were before
# redirection or used themselves to output to whatever they were before the
# following redirect.
exec 3>&1 4>&2
# Restore file descriptors for particular signals. Not generally necessary
# since they should be restored when the sub-shell exits.
trap 'exec 2>&4 1>&3' 0 1 2 3
# Redirect stdout to log file then redirect stderr to stdout.
# Note that the order is important when you want them going to the same file.
# stdout must be redirected before stderr is redirected to stdout.
exec 1>docker_installation.log 2>&1

# Update package lists and install prerequisites
echo -e "--> Updating package lists and installing prerequisites...\n" >> docker_installation.log
sudo apt update
sudo apt install ca-certificates curl gnupg

# Add Docker’s official GPG key
echo -e "--> Adding Docker’s official GPG key...\n" >> docker_installation.log
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Set up the repository: This command automatically detects your architecture and Ubuntu version (which should be noble for 24.04)
echo -e "--> Setting up the repository...\n" >> docker_installation.log
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Update package lists again (to include Docker repo)
sudo apt update

# Install Docker Engine, CLI, containerd, and Docker Compose plugin
# docker-ce: The Docker Engine daemon.
# docker-ce-cli: The Docker command-line interface.   
# containerd.io: A container runtime.
# docker-buildx-plugin: Enables advanced build features with BuildKit.   
# docker-compose-plugin: Installs Docker Compose V2, allowing you to use docker compose (with a space).
echo -e "--> Installing Docker Engine, CLI, containerd, and Docker Compose plugin...\n" >> docker_installation.log
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Check that the Docker service is running
echo -e "--> Checking that the Docker service is running...\n" >> docker_installation.log
sudo systemctl status docker
sudo docker run hello-world

# By default, the docker command requires root privileges (sudo). 
# To run docker commands without sudo, add your user to the docker group.
# You need to log out and log back in for this group membership change.
echo -e "--> Adding user to the docker group...\n" >> docker_installation.log
sudo groupadd docker # This might already exist, which is fine
sudo usermod -aG docker $USER
