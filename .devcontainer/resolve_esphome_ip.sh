#!/bin/bash

# Resolve ESPHOME_IP from ESP_HOME_HOSTNAME by pinging ${ESP_HOME_HOSTNAME}.local
# This script is designed to be used as an entrypoint in Docker containers

if [ -n "$ESP_HOME_HOSTNAME" ]; then
  echo "ESP_HOME_HOSTNAME is set to: $ESP_HOME_HOSTNAME"
  
  # Try to ping the hostname.local and extract IP
  PING_OUTPUT=$(ping -c 1 "${ESP_HOME_HOSTNAME}.local" 2>/dev/null || true)
  
  if [ -n "$PING_OUTPUT" ]; then
    # Try to extract IP from ping output (works for standard ping)
    ESPHOME_IP=$(echo "$PING_OUTPUT" | head -n 1 | grep -oE "\b([0-9]{1,3}\.){3}[0-9]{1,3}\b" | head -n 1)
  fi
  
  # If ping failed, try host command as fallback
  if [ -z "$ESPHOME_IP" ]; then
    echo "Ping failed, trying host command..."
    ESPHOME_IP=$(host "${ESP_HOME_HOSTNAME}.local" 2>/dev/null | grep -oE "\b([0-9]{1,3}\.){3}[0-9]{1,3}\b" | head -n 1)
  fi
  
  # If still not found, try getent as another fallback
  if [ -z "$ESPHOME_IP" ]; then
    echo "Host command failed, trying getent..."
    ESPHOME_IP=$(getent hosts "${ESP_HOME_HOSTNAME}.local" 2>/dev/null | grep -oE "\b([0-9]{1,3}\.){3}[0-9]{1,3}\b" | head -n 1)
  fi
  
  if [ -n "$ESPHOME_IP" ]; then
    echo "export ESPHOME_IP=$ESPHOME_IP" > /root/.esphome_env
    echo "Resolved ESPHOME_IP: $ESPHOME_IP"
  else
    echo "Warning: Could not resolve IP for ${ESP_HOME_HOSTNAME}.local"
  fi
fi

exec "$@"
