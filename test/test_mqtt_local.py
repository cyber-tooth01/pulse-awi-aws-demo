#!/usr/bin/env python3
"""
Local MQTT testing script - subscribes to Meshtastic MQTT and displays messages
Run this to verify your MQTT topic is receiving sensor data before deploying to AWS
"""

import paho.mqtt.client as mqtt
import json
import sys
import os
import base64
import hashlib
from Crypto.Cipher import AES

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

# Meshtastic encryption PSK (base64-encoded)
MESHTASTIC_PSK_B64 = os.environ.get('MESHTASTIC_PSK', 'Sw==')
try:
    MESHTASTIC_PSK = base64.b64decode(MESHTASTIC_PSK_B64)
except Exception as e:
    print(f"⚠ Failed to decode PSK: {e}")
    MESHTASTIC_PSK = base64.b64decode('Sw==')

def decrypt_payload(encrypted_bytes, psk):
    """Decrypt Meshtastic AES-128-CTR encrypted payload.

    Meshtastic derives a 128-bit key from the PSK using SHA256 (first 16 bytes).
    The nonce is the first 4 bytes of the payload; remaining bytes are ciphertext.
    IV for CTR = nonce (4B) + 12 zero bytes.
    """
    try:
        if len(encrypted_bytes) < 4:
            return None
        nonce = encrypted_bytes[:4]
        ciphertext = encrypted_bytes[4:]
        iv = nonce + b'\x00' * 12
        key = hashlib.sha256(psk).digest()[:16]
        cipher = AES.new(key, AES.MODE_CTR, nonce=iv[:12])
        return cipher.decrypt(ciphertext)
    except Exception as e:
        print(f"   Decryption error: {e}")
        return None

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

                # Extract node ID - handle both 'from_' and 'from' attributes, including zero values
                from_id = None
                if hasattr(envelope.packet, 'from_'):
                    from_id = envelope.packet.from_
                elif hasattr(envelope.packet, 'from'):
                    from_id = getattr(envelope.packet, 'from')
                
                sender_id = f"!{from_id:08x}" if from_id is not None else "unknown"
                print(f"   Sender: {sender_id}")
                
                # Check if message has decoded field (unencrypted) or encrypted field
                if not envelope.packet.HasField('decoded'):
                    print(f"   🔒 Encrypted message (no decoded field)")
                    
                    # Try to decrypt if we have encrypted data
                    if envelope.packet.HasField('encrypted'):
                        print(f"   Attempting decryption...")
                        print(f"   PSK length: {len(MESHTASTIC_PSK)} bytes")
                        decrypted = decrypt_payload(bytes(envelope.packet.encrypted), MESHTASTIC_PSK)
                        if decrypted:
                            # Use errors='ignore' for decrypted data as it may have padding/noise
                            text_payload = decrypted.decode('utf-8', errors='ignore')
                            print(f"   ✓ Decryption successful (decrypted {len(decrypted)} bytes)")
                            
                            if text_payload.strip().startswith('{'):
                                try:
                                    sensor_data = json.loads(text_payload)
                                    print(f"   📊 Decrypted Sensor Data:")
                                    print(f"      PM2.5: {sensor_data.get('pm25')} µg/m³")
                                    print(f"      PM10:  {sensor_data.get('pm10')} µg/m³")
                                    print(f"      VOC:   {sensor_data.get('voc')}")
                                    print(f"      NOx:   {sensor_data.get('nox')}")
                                    print(f"      Temp:  {sensor_data.get('t')}°C")
                                    print(f"      RH:    {sensor_data.get('rh')}%")
                                except json.JSONDecodeError:
                                    print(f"   Decrypted text: {text_payload[:100]}")
                        else:
                            print(f"   ✗ Decryption failed")
                    # Skip further processing for encrypted messages
                    print()
                    return
                
                # Message has decoded field - process it
                port = envelope.packet.decoded.portnum
                print(f"   Port: {port}")
                
                payload_bytes = envelope.packet.decoded.payload
                
                # Handle different port types
                if port == portnums_pb2.PortNum.TEXT_MESSAGE_APP:
                    # Port 1: TEXT_MESSAGE_APP - JSON text
                    text_payload = None
                    
                    # Decode as UTF-8 text
                    try:
                        text_payload = payload_bytes.decode('utf-8', errors='strict')
                    except UnicodeDecodeError:
                        print(f"   ⚠ Could not decode payload as UTF-8")
                        print(f"   Hex dump (first 32 bytes): {payload_bytes[:32].hex()}")
                        return

                    if text_payload:
                        preview = (text_payload[:100] + '...') if len(text_payload) > 100 else text_payload
                        print(f"   Text payload: {preview}")

                        if text_payload.strip().startswith('{'):
                            try:
                                sensor_data = json.loads(text_payload)
                                print(f"   📊 Sensor Data (from JSON):")
                                print(f"      PM2.5: {sensor_data.get('pm25')} µg/m³")
                                print(f"      PM10:  {sensor_data.get('pm10')} µg/m³")
                                print(f"      VOC:   {sensor_data.get('voc')}")
                                print(f"      NOx:   {sensor_data.get('nox')}")
                                print(f"      Temp:  {sensor_data.get('t')}°C")
                                print(f"      RH:    {sensor_data.get('rh')}%")
                            except json.JSONDecodeError as e:
                                print(f"   ⚠ Text looks like JSON but failed to parse: {e}")
                    else:
                        print("   ⚠ No text payload present in protobuf message")
                
                elif port == portnums_pb2.PortNum.TELEMETRY_APP:
                    # Port 67: TELEMETRY_APP - Binary protobuf telemetry
                    try:
                        telemetry = telemetry_pb2.Telemetry()
                        telemetry.ParseFromString(payload_bytes)
                        
                        if telemetry.HasField('air_quality_metrics'):
                            aq = telemetry.air_quality_metrics
                            print(f"   📊 Air Quality Telemetry:")
                            print(f"      PM1.0:       {aq.pm10_standard} µg/m³")
                            print(f"      PM2.5:       {aq.pm25_standard} µg/m³")
                            print(f"      PM4.0:       {aq.pm40_standard} µg/m³")
                            print(f"      PM10:        {aq.pm100_standard} µg/m³")
                            print(f"      VOC Index:   {aq.pm_voc_idx}")
                            print(f"      NOx Index:   {aq.pm_nox_idx}")
                            print(f"      Temp:        {aq.pm_temperature}°C")
                            print(f"      Humidity:    {aq.pm_humidity}%")
                        else:
                            print(f"   ℹ Telemetry type: {telemetry.WhichOneof('variant')}")
                            if telemetry.HasField('device_metrics'):
                                dm = telemetry.device_metrics
                                print(f"      Battery: {dm.battery_level}%")
                                print(f"      Voltage: {dm.voltage}V")
                            elif telemetry.HasField('environment_metrics'):
                                em = telemetry.environment_metrics
                                print(f"      Temperature: {em.temperature}°C")
                                print(f"      Humidity: {em.relative_humidity}%")
                                print(f"      Pressure: {em.barometric_pressure} hPa")
                    except Exception as e:
                        print(f"   ⚠ Could not decode telemetry: {e}")
                        print(f"   Hex dump (first 32 bytes): {payload_bytes[:32].hex()}")
                
                else:
                    # Other port types
                    print(f"   ℹ Unsupported port type {port}")
                    print(f"   Hex dump (first 32 bytes): {payload_bytes[:32].hex()}")

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
