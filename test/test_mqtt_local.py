#!/usr/bin/env python3
"""
Local MQTT testing script - subscribes to Meshtastic MQTT and displays messages
Run this to verify your MQTT topic is receiving sensor data before deploying to AWS
"""

import paho.mqtt.client as mqtt
import json
import sys

try:
    from meshtastic.protobuf import mqtt_pb2, portnums_pb2, telemetry_pb2
    PROTOBUF_AVAILABLE = True
except ImportError:
    print("⚠ Warning: meshtastic package not installed. Install with: pip install meshtastic")
    PROTOBUF_AVAILABLE = False

MQTT_BROKER = "mqtt.meshtastic.org"
MQTT_PORT = 1883
MQTT_TOPIC = "msh/US/2/e/pulse-aqi/#"
MQTT_USERNAME = "meshdev"
MQTT_PASSWORD = "large4cats"

def on_connect(client, userdata, flags, rc):
    """MQTT connection callback"""
    if rc == 0:
        print(f"✓ Connected to MQTT broker: {MQTT_BROKER}")
        client.subscribe(MQTT_TOPIC)
        print(f"✓ Subscribed to topic: {MQTT_TOPIC}")
        print("\nListening for messages (Ctrl+C to stop)...\n")
    else:
        print(f"✗ Connection failed with code {rc}")
        sys.exit(1)

def on_message(client, userdata, msg):
    """MQTT message callback"""
    try:
        print(f"📬 Message from {msg.topic}")
        print(f"   Payload length: {len(msg.payload)} bytes")
        
        # Try to decode as UTF-8 text/JSON first
        try:
            payload_str = msg.payload.decode('utf-8')
            
            # Check if it's JSON
            if payload_str.startswith('{'):
                payload = json.loads(payload_str)
                print(f"   Format: JSON")
                process_json_payload(payload)
            else:
                print(f"   Format: Plain Text")
                print(f"   Content: {payload_str}")
                
        except UnicodeDecodeError:
            # Binary data - decode protobuf
            print(f"   Format: Binary Protobuf")
            
            if not PROTOBUF_AVAILABLE:
                print(f"   ⚠ Cannot decode: meshtastic package not installed")
                print(f"   Install with: pip install meshtastic")
                return
            
            try:
                # Decode Meshtastic ServiceEnvelope
                envelope = mqtt_pb2.ServiceEnvelope()
                envelope.ParseFromString(msg.payload)
                
                sender_id = f"!{envelope.packet.from_:08x}" if envelope.packet.from_ else "unknown"
                print(f"   Sender: {sender_id}")
                print(f"   Port: {envelope.packet.decoded.portnum}")
                
                # Check if it's a TEXT_MESSAGE_APP
                if envelope.packet.decoded.portnum == portnums_pb2.PortNum.TEXT_MESSAGE_APP:
                    text_payload = envelope.packet.decoded.payload.decode('utf-8')
                    print(f"   Text payload: {text_payload[:100]}..." if len(text_payload) > 100 else f"   Text payload: {text_payload}")
                    
                    # Try to parse as JSON sensor data
                    if text_payload.strip().startswith('{'):
                        try:
                            sensor_data = json.loads(text_payload)
                            print(f"   📊 Sensor Data:")
                            print(f"      PM2.5: {sensor_data.get('pm25')} µg/m³")
                            print(f"      PM10:  {sensor_data.get('pm10')} µg/m³")
                            print(f"      VOC:   {sensor_data.get('voc')}")
                            print(f"      NOx:   {sensor_data.get('nox')}")
                            print(f"      Temp:  {sensor_data.get('t')}°C")
                            print(f"      RH:    {sensor_data.get('rh')}%")
                        except json.JSONDecodeError as e:
                            print(f"   ⚠ Text looks like JSON but failed to parse: {e}")
                else:
                    print(f"   ⚠ Not a text message (port {envelope.packet.decoded.portnum})")
                    
            except Exception as e:
                print(f"   ✗ Protobuf decode error: {e}")
                print(f"   Hex dump (first 64 bytes): {msg.payload[:64].hex()}")
        
        print()
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        print()

def process_json_payload(payload):
    """Process JSON format payload"""
    print(f"   Type: {payload.get('type', 'unknown')}")
    print(f"   Sender: {payload.get('sender', 'unknown')}")
    
    if payload.get('type') == 'text':
        text = payload.get('payload', {}).get('text', '')
        if text.startswith('{'):
            try:
                sensor_data = json.loads(text)
                print(f"   📊 Sensor Data:")
                print(f"      PM2.5: {sensor_data.get('pm25')} µg/m³")
                print(f"      PM10:  {sensor_data.get('pm10')} µg/m³")
                print(f"      VOC:   {sensor_data.get('voc')}")
                print(f"      NOx:   {sensor_data.get('nox')}")
                print(f"      Temp:  {sensor_data.get('t')}°C")
                print(f"      RH:    {sensor_data.get('rh')}%")
            except json.JSONDecodeError:
                print(f"   Text: {text}")
        else:
            print(f"   Text: {text}")

def main():
    print("PulseAQI MQTT Test Client")
    print("=" * 60)
    print(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Topic:  {MQTT_TOPIC}")
    print("=" * 60)
    
    client = mqtt.Client(client_id="pulseaqi-test-client")
    client.on_connect = on_connect
    client.on_message = on_message
    
    # Set authentication credentials
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        client.disconnect()
    except Exception as e:
        print(f"✗ Connection error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
