#!/usr/bin/env python3
"""
Meshtastic MQTT decoder
- Subscribes to MQTT broker and decodes Meshtastic protobuf ServiceEnvelope
- Prints structured info: sender, channel, port name, RSSI/SNR, and payload
- Decodes TEXT_MESSAGE_APP payload as UTF-8 and tries to parse JSON sensor data

Usage:
  pip install -r requirements.txt
  python tools/decode_mqtt.py
"""

import sys
import json
import time
import paho.mqtt.client as mqtt

MQTT_BROKER = "mqtt.meshtastic.org"
MQTT_PORT = 1883
MQTT_TOPIC = "msh/US/2/e/pulse-aqi/#"
MQTT_USERNAME = "meshdev"
MQTT_PASSWORD = "large4cats"

# Protobuf imports
try:
    from meshtastic.protobuf import mqtt_pb2, portnums_pb2
    PROTOBUF_AVAILABLE = True
except ImportError:
    print("✗ meshtastic package not installed. Install with: pip install meshtastic")
    PROTOBUF_AVAILABLE = False

PORT_NAMES = {v: k for k, v in portnums_pb2.PortNum.__dict__.items() if isinstance(v, int)}

def port_name(portnum: int) -> str:
    return PORT_NAMES.get(portnum, f"UNKNOWN({portnum})")


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"✓ Connected: {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC)
        print(f"✓ Subscribed: {MQTT_TOPIC}\n")
        print("Listening (Ctrl+C to stop)\n")
    else:
        print(f"✗ Connect failed: {rc}")
        sys.exit(1)


def print_sensor_data(sensor: dict):
    print("   📊 Sensor Data:")
    for k in ["pm1", "pm25", "pm4", "pm10", "voc", "nox", "t", "rh"]:
        if k in sensor:
            print(f"      {k}: {sensor[k]}")


def on_message(client, userdata, msg):
    try:
        payload = msg.payload
        print(f"📬 Topic: {msg.topic}")
        print(f"   Bytes: {len(payload)}")

        # First try JSON
        try:
            s = payload.decode("utf-8")
            if s.startswith("{"):
                j = json.loads(s)
                print("   Format: JSON")
                print(f"   Type: {j.get('type')} Sender: {j.get('sender')} Channel: {j.get('channel', '-')}")
                if j.get("type") == "text":
                    text = j.get("payload", {}).get("text", "")
                    print(f"   Text: {text[:120]}" + ("..." if len(text) > 120 else ""))
                    if text.strip().startswith("{"):
                        try:
                            sensor = json.loads(text)
                            print_sensor_data(sensor)
                        except json.JSONDecodeError:
                            pass
                print()
                return
        except UnicodeDecodeError:
            pass

        # Protobuf decode
        if not PROTOBUF_AVAILABLE:
            print("   Binary payload (protobuf). Install meshtastic to decode.")
            print(f"   Hex[0:64]: {payload[:64].hex()}\n")
            return

        env = mqtt_pb2.ServiceEnvelope()
        env.ParseFromString(payload)

        sender = f"!{env.packet.from_:08x}" if env.packet.from_ else "unknown"
        channel = env.channel or ""
        rssi = env.rssi if env.rssi else 0
        snr = env.snr if env.snr else 0
        port = env.packet.decoded.portnum if env.packet.HasField("decoded") else None
        enc = env.packet.HasField("encrypted")

        print(f"   Sender: {sender}")
        print(f"   Channel: {channel}")
        print(f"   RSSI/SNR: {rssi} dBm / {snr} dB")
        if port is not None:
            print(f"   Port: {port_name(port)}")
        print(f"   Encrypted: {'yes' if enc else 'no'}")

        if port == portnums_pb2.PortNum.TEXT_MESSAGE_APP and env.packet.decoded.payload:
            try:
                text = env.packet.decoded.payload.decode("utf-8")
                print(f"   Text: {text[:200]}" + ("..." if len(text) > 200 else ""))
                if text.strip().startswith("{"):
                    try:
                        sensor = json.loads(text)
                        print_sensor_data(sensor)
                    except json.JSONDecodeError:
                        print("   (Text not valid JSON)")
            except Exception as e:
                print(f"   ✗ Text decode error: {e}")
        else:
            # Other ports: show payload length
            if env.packet.HasField("decoded") and env.packet.decoded.payload:
                print(f"   Decoded payload bytes: {len(env.packet.decoded.payload)}")
            elif env.packet.HasField("encrypted"):
                print("   ⚠ Encrypted payload present (channel key required)")

        print()

    except Exception as e:
        print(f"✗ Error: {e}\n")


def main():
    client = mqtt.Client(client_id="pulseaqi-decoder")
    client.on_connect = on_connect
    client.on_message = on_message
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        client.disconnect()
    except Exception as e:
        print(f"✗ Connection error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
