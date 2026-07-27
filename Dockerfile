# Builds a NetBox image with the Cisco Sync plugin installed.
#
# The local lab can override NETBOX_IMAGE from compose.yaml. The default matches
# the current production NetBox version.
ARG NETBOX_IMAGE=netboxcommunity/netbox:v4.6.3
FROM ${NETBOX_IMAGE}

ARG PLUGIN_DIR=/opt/netbox-cisco-sync

COPY . ${PLUGIN_DIR}
RUN /usr/local/bin/uv pip install --no-cache \
    --python /opt/netbox/venv/bin/python \
    --editable ${PLUGIN_DIR}
