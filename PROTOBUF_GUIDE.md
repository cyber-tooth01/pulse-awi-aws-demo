# Meshtastic Protobuf Decoding Guide

## Overview

This guide explains how the PulseAQI system decodes Meshtastic protobuf messages from MQTT. The Meshtastic network sends binary protobuf messages instead of JSON when using nRF52-based nodes.

## Why Protobuf?

- **nRF52 Limitation**: These microcontrollers don't have sufficient resources for JSON encoding
- **Bandwidth Efficiency**: Protobuf messages are smaller than JSON (important for LoRa)
- **Standard Protocol**: Meshtastic uses protobuf across all platforms

## Message Structure

### MQTT Topic
```
msh/US/2/e/pulse-aqi/#
```
- `msh`: Meshtastic prefix
- `US`: Region
- `2`: Channel (default public channel)
- `e`: Encryption (downlink encryption - we don't use this)
- `pulse-aqi`: Channel name
- `#`: Wildcard for all sub-topics (nodes)

### Protobuf Message Hierarchy

```
ServiceEnvelope (mqtt_pb2)
├── packet: MeshPacket (mesh_pb2)
│   ├── from: uint32 (node ID)
│   ├── to: uint32 (destination, 0xffffffff for broadcast)
│   ├── decoded: Data (for unencrypted messages)
│   │   ├── portnum: PortNum enum
│   │   └── payload: bytes (actual data)
│   └── encrypted: bytes (for encrypted messages - we skip these)
├── channel_id: string
└── gateway_id: string
```

## Port Numbers

Port numbers identify the type of message:

| Port | Name | Value | Purpose |
|------|------|-------|---------|
| TEXT_MESSAGE_APP | 1 | **Our sensor data** - JSON in UTF-8 text |
| POSITION_APP | 3 | GPS location data |
| TELEMETRY_APP | 67 | Device telemetry (battery, voltage, etc.) |
| PRIVATE_APP | 256 | Private application data |

**For PulseAQI**: We only process port 1 (TEXT_MESSAGE_APP) messages.

## Decoding Process

### 1. Parse ServiceEnvelope

```python
from meshtastic.protobuf import mqtt_pb2

envelope = mqtt_pb2.ServiceEnvelope()
envelope.ParseFromString(msg.payload)  # msg.payload is binary MQTT payload
```

### 2. Extract Node ID

```python
# Handle both 'from' and 'from_' field variants (from is a Python keyword)
from_id = None
if hasattr(envelope.packet, 'from_'):
    from_id = envelope.packet.from_
elif hasattr(envelope.packet, 'from'):
    from_id = getattr(envelope.packet, 'from')

node_id = f"!{from_id:08x}" if from_id is not None else None
# Result: "!e70287b5"
```

### 3. Check for Encryption

```python
# Skip encrypted messages (we require encryption to be OFF)
if not envelope.packet.HasField('decoded'):
    logger.debug("Skipping encrypted message")
    return
```

### 4. Validate Port Number

```python
from meshtastic.protobuf import portnums_pb2

port = envelope.packet.decoded.portnum

# Only process TEXT_MESSAGE_APP (port 1)
if port != portnums_pb2.PortNum.TEXT_MESSAGE_APP:
    logger.debug(f"Skipping port {port}")
    return
```

### 5. Decode Payload

```python
# Extract binary payload
payload_bytes = envelope.packet.decoded.payload

# Decode as UTF-8 text
text_payload = payload_bytes.decode('utf-8', errors='strict')

# Parse JSON sensor data
sensor_data = json.loads(text_payload)
```

### 6. Expected Sensor Data Format

```json
{
  "pm1": 3,
  "pm25": 4,
  "pm4": 5,
  "pm10": 5,
  "voc": 103.0,
  "nox": 1.0,
  "t": 24.7,
  "rh": 63.8
}
```

## Complete Example

```python
from meshtastic.protobuf import mqtt_pb2, portnums_pb2
import json

def on_message(client, userdata, msg):
    try:
        # Parse protobuf
        envelope = mqtt_pb2.ServiceEnvelope()
        envelope.ParseFromString(msg.payload)
        
        # Extract node ID
        from_id = getattr(envelope.packet, 'from', None)
        if not from_id:
            from_id = getattr(envelope.packet, 'from_', None)
        node_id = f"!{from_id:08x}" if from_id is not None else None
        
        # Check for encryption
        if not envelope.packet.HasField('decoded'):
            print("Encrypted message - skipping")
            return
        
        # Check port
        port = envelope.packet.decoded.portnum
        if port != portnums_pb2.PortNum.TEXT_MESSAGE_APP:
            print(f"Not a TEXT message (port {port}) - skipping")
            return
        
        # Decode payload
        payload_bytes = envelope.packet.decoded.payload
        text = payload_bytes.decode('utf-8')
        
        # Parse JSON
        sensor_data = json.loads(text)
        
        print(f"Node {node_id}: PM2.5 = {sensor_data['pm25']} µg/m³")
        
    except Exception as e:
        print(f"Error: {e}")
```

## Testing

### Unit Tests

Run protobuf decoding tests:
```bash
python3 test/test_protobuf_decode.py
```

This validates:
- Node ID extraction (including zero values)
- Protobuf encoding/decoding
- Port number filtering
- Malformed payload handling
- Encrypted vs unencrypted detection

### Integration Tests

Run integration tests:
```bash
python3 test/test_mqtt_bridge_integration.py
```

This validates:
- End-to-end message processing
- Port filtering logic
- Required field validation
- AQI calculation from decoded data

### Live MQTT Testing

Monitor live MQTT messages:
```bash
python3 test/test_mqtt_local.py
```

This connects to the actual MQTT broker and shows decoded messages in real-time.

## Troubleshooting

### Issue: "meshtastic package not installed"

```bash
pip install meshtastic>=2.2.0
```

### Issue: "Skipping encrypted message"

**Cause**: The Meshtastic node is sending encrypted messages.

**Solution**: Disable encryption on the mesh network:
1. Connect to the Meshtastic node with the Meshtastic CLI or app
2. Set encryption key to default: `--set channel.psk base64:Sw==`
3. Or use the channel named "pulse-aqi" with encryption disabled

### Issue: "Port X is not TEXT_MESSAGE_APP"

**Cause**: The node is sending telemetry or position data instead of text.

**Solution**: Ensure the sensor data is being sent via the TEXT port (port 1).

### Issue: "UTF-8 decode error"

**Cause**: The payload is not valid UTF-8 text.

**Solutions**:
- Check that encryption is truly disabled
- Verify the sensor is sending JSON text, not binary data
- Check for transmission errors on the LoRa mesh

### Issue: "JSON parse error"

**Cause**: The text payload is not valid JSON.

**Solutions**:
- Verify sensor data format matches expected schema
- Check for incomplete transmissions (signal issues)
- Validate JSON on the sending node before transmission

## Meshtastic Configuration

### Recommended Settings for PulseAQI

```bash
# Set channel name
meshtastic --ch-set name pulse-aqi --ch-index 0

# Disable encryption (use default PSK)
# ⚠️ SECURITY WARNING: This makes all mesh communications publicly readable!
# Only use for non-sensitive environmental sensor data.
# For private data, use a strong custom PSK instead.
meshtastic --ch-set psk base64:Sw== --ch-index 0

# Set uplink/downlink
meshtastic --ch-set uplink_enabled true --ch-index 0
meshtastic --ch-set downlink_enabled false --ch-index 0

# Enable MQTT
meshtastic --set mqtt.enabled true
meshtastic --set mqtt.address mqtt.meshtastic.org
```

### Sensor Node Code

On the nRF52 Meshtastic node, send sensor data like this:

```cpp
// C++ example for nRF52
#include <mesh/mesh-pb-constants.h>

String sensorJson = "{\"pm1\":3,\"pm25\":4,\"pm4\":5,\"pm10\":5,\"voc\":103.0,\"nox\":1.0,\"t\":24.7,\"rh\":63.8}";

meshtastic_MeshPacket packet = {
    .to = NODENUM_BROADCAST,
    .decoded = {
        .portnum = meshtastic_PortNum_TEXT_MESSAGE_APP,  // Port 1
        .payload = {
            .size = sensorJson.length(),
            .bytes = (uint8_t*)sensorJson.c_str()
        }
    }
};

service.sendToMesh(packet);
```

## References

- [Meshtastic MQTT Documentation](https://meshtastic.org/docs/software/integrations/mqtt/)
- [Meshtastic Protobuf Definitions](https://github.com/meshtastic/protobufs)
- [Protocol Buffers Documentation](https://protobuf.dev/)
- [Python meshtastic Package](https://pypi.org/project/meshtastic/)

## Appendix: All Port Numbers

```python
from meshtastic.protobuf import portnums_pb2

# Full list of port numbers
UNKNOWN_APP = 0
TEXT_MESSAGE_APP = 1                    # ← We use this
REMOTE_HARDWARE_APP = 2
POSITION_APP = 3
NODEINFO_APP = 4
ROUTING_APP = 5
ADMIN_APP = 6
TEXT_MESSAGE_COMPRESSED_APP = 7
WAYPOINT_APP = 8
AUDIO_APP = 9
DETECTION_SENSOR_APP = 10
ALERT_APP = 11
KEY_VERIFICATION_APP = 12
REPLY_APP = 32
IP_TUNNEL_APP = 33
PAXCOUNTER_APP = 34
STORE_FORWARD_PLUSPLUS_APP = 35
NODE_STATUS_APP = 36
SERIAL_APP = 64
STORE_FORWARD_APP = 65
RANGE_TEST_APP = 66
TELEMETRY_APP = 67
ZPS_APP = 68
SIMULATOR_APP = 69
TRACEROUTE_APP = 70
NEIGHBORINFO_APP = 71
ATAK_PLUGIN = 72
MAP_REPORT_APP = 73
POWERSTRESS_APP = 74
RETICULUM_TUNNEL_APP = 76
CAYENNE_APP = 77
PRIVATE_APP = 256
ATAK_FORWARDER = 257
MAX = 511
```
