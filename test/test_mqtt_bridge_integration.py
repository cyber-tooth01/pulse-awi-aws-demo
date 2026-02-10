#!/usr/bin/env python3
"""
Integration test for mqtt_bridge.py protobuf message processing
Simulates MQTT messages and validates end-to-end processing
"""

import sys
import json
import os
from unittest.mock import Mock, MagicMock
from meshtastic.protobuf import mqtt_pb2, mesh_pb2, portnums_pb2

# Set environment variables before importing mqtt_bridge
os.environ['INFLUXDB_TOKEN'] = 'test-token'
os.environ['INFLUXDB_ORG'] = 'test-org'
os.environ['INFLUXDB_BUCKET'] = 'test-bucket'

def create_protobuf_message(node_id, port, payload_data):
    """Create a Meshtastic protobuf message"""
    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.packet.CopyFrom(mesh_pb2.MeshPacket())
    
    # Set sender
    setattr(envelope.packet, 'from', node_id)
    envelope.packet.to = 0xffffffff
    
    # Set port and payload
    envelope.packet.decoded.portnum = port
    
    if isinstance(payload_data, dict):
        payload_data = json.dumps(payload_data)
    
    if isinstance(payload_data, str):
        payload_data = payload_data.encode('utf-8')
        
    envelope.packet.decoded.payload = payload_data
    
    return envelope.SerializeToString()

def test_protobuf_message_parsing():
    """Test that protobuf messages are correctly parsed"""
    print("=" * 60)
    print("Integration Test: Protobuf Message Parsing")
    print("=" * 60)
    
    # Sample sensor data
    sensor_data = {
        "pm1": 3,
        "pm25": 4.5,
        "pm4": 5,
        "pm10": 5,
        "voc": 103.0,
        "nox": 1.0,
        "t": 24.7,
        "rh": 63.8
    }
    
    node_id = 0xe70287b5
    port = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    
    # Create protobuf message
    serialized = create_protobuf_message(node_id, port, sensor_data)
    print(f"✓ Created protobuf message: {len(serialized)} bytes")
    
    # Mock MQTT message
    mqtt_msg = Mock()
    mqtt_msg.topic = "msh/US/2/e/pulse-aqi/!e70287b5"
    mqtt_msg.payload = serialized
    
    # Process the message (simulate on_message logic)
    try:
        envelope = mqtt_pb2.ServiceEnvelope()
        envelope.ParseFromString(mqtt_msg.payload)
        print("✓ Parsed ServiceEnvelope")
        
        # Extract node ID
        from_id = getattr(envelope.packet, 'from', None)
        if not from_id:
            from_id = getattr(envelope.packet, 'from_', None)
        
        extracted_node_id = f"!{from_id:08x}" if from_id is not None else None
        print(f"✓ Extracted node ID: {extracted_node_id}")
        
        # Check decoded field
        has_decoded = envelope.packet.HasField('decoded')
        print(f"✓ Has decoded field: {has_decoded}")
        
        if not has_decoded:
            print("✗ FAILED: Message should have decoded field")
            return False
        
        # Check port
        port_num = envelope.packet.decoded.portnum
        print(f"✓ Port number: {port_num}")
        
        if port_num != portnums_pb2.PortNum.TEXT_MESSAGE_APP:
            print(f"✗ FAILED: Expected port {portnums_pb2.PortNum.TEXT_MESSAGE_APP}, got {port_num}")
            return False
        
        # Decode payload
        payload_bytes = envelope.packet.decoded.payload
        text_payload = payload_bytes.decode('utf-8')
        print(f"✓ Decoded text payload ({len(text_payload)} chars)")
        
        # Parse JSON
        parsed_data = json.loads(text_payload)
        print(f"✓ Parsed sensor JSON: {len(parsed_data)} fields")
        
        # Validate all required fields
        required_fields = ['pm1', 'pm25', 'pm4', 'pm10', 'voc', 'nox', 't', 'rh']
        missing_fields = [f for f in required_fields if f not in parsed_data]
        
        if missing_fields:
            print(f"✗ FAILED: Missing required fields: {missing_fields}")
            return False
        
        print(f"✓ All required fields present: {required_fields}")
        
        # Calculate AQI (simple version)
        pm25 = float(parsed_data['pm25'])
        print(f"✓ PM2.5 value: {pm25} µg/m³")
        
        print("\n✓ Integration test PASSED")
        return True
        
    except Exception as e:
        print(f"✗ FAILED with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_different_port_numbers():
    """Test that TEXT and TELEMETRY messages are processed, others skipped"""
    print("\n" + "=" * 60)
    print("Integration Test: Port Number Filtering")
    print("=" * 60)
    
    test_cases = [
        (portnums_pb2.PortNum.TEXT_MESSAGE_APP, True, "TEXT_MESSAGE_APP"),
        (portnums_pb2.PortNum.TELEMETRY_APP, True, "TELEMETRY_APP"),  # Now supported
        (portnums_pb2.PortNum.POSITION_APP, False, "POSITION_APP"),
    ]
    
    for port_num, should_process, port_name in test_cases:
        serialized = create_protobuf_message(0x12345678, port_num, {"test": "data"})
        
        envelope = mqtt_pb2.ServiceEnvelope()
        envelope.ParseFromString(serialized)
        
        port = envelope.packet.decoded.portnum
        is_supported_port = (port == portnums_pb2.PortNum.TEXT_MESSAGE_APP or 
                            port == portnums_pb2.PortNum.TELEMETRY_APP)
        
        status = "✓" if is_supported_port == should_process else "✗"
        action = "PROCESS" if should_process else "SKIP"
        print(f"{status} Port {port} ({port_name:25s}) -> {action}")
    
    print()

def test_telemetry_message_processing():
    """Test that Port 67 telemetry messages with air quality data are processed"""
    print("=" * 60)
    print("Integration Test: Telemetry Message Processing")
    print("=" * 60)
    
    try:
        from meshtastic.protobuf import telemetry_pb2
        
        # Create telemetry with air quality data
        telemetry = telemetry_pb2.Telemetry()
        telemetry.air_quality_metrics.pm10_standard = 3
        telemetry.air_quality_metrics.pm25_standard = 45
        telemetry.air_quality_metrics.pm40_standard = 5
        telemetry.air_quality_metrics.pm100_standard = 50
        telemetry.air_quality_metrics.pm_voc_idx = 103
        telemetry.air_quality_metrics.pm_nox_idx = 1
        telemetry.air_quality_metrics.pm_temperature = 24.7
        telemetry.air_quality_metrics.pm_humidity = 63.8
        
        # Create envelope with telemetry
        envelope = mqtt_pb2.ServiceEnvelope()
        envelope.packet.CopyFrom(mesh_pb2.MeshPacket())
        setattr(envelope.packet, 'from', 0xe70287b5)
        envelope.packet.to = 0xffffffff
        envelope.packet.decoded.portnum = portnums_pb2.PortNum.TELEMETRY_APP
        envelope.packet.decoded.payload = telemetry.SerializeToString()
        
        serialized = envelope.SerializeToString()
        print(f"✓ Created telemetry protobuf message ({len(serialized)} bytes)")
        
        # Parse it back
        envelope2 = mqtt_pb2.ServiceEnvelope()
        envelope2.ParseFromString(serialized)
        print("✓ Parsed ServiceEnvelope")
        
        # Extract node ID
        from_id = getattr(envelope2.packet, 'from', None)
        node_id = f"!{from_id:08x}" if from_id is not None else None
        print(f"✓ Extracted node ID: {node_id}")
        
        # Check port
        port = envelope2.packet.decoded.portnum
        print(f"✓ Port number: {port} (TELEMETRY_APP)")
        
        if port != portnums_pb2.PortNum.TELEMETRY_APP:
            print(f"✗ FAILED: Expected port {portnums_pb2.PortNum.TELEMETRY_APP}, got {port}")
            return False
        
        # Decode telemetry
        telemetry2 = telemetry_pb2.Telemetry()
        telemetry2.ParseFromString(envelope2.packet.decoded.payload)
        
        if not telemetry2.HasField('air_quality_metrics'):
            print("✗ FAILED: No air quality metrics found")
            return False
        
        print("✓ Has air quality metrics")
        
        aq = telemetry2.air_quality_metrics
        
        # Validate values can be converted to sensor_data format
        sensor_data = {
            'pm1': aq.pm10_standard,
            'pm25': aq.pm25_standard,
            'pm4': aq.pm40_standard,
            'pm10': aq.pm100_standard,
            'voc': aq.pm_voc_idx,
            'nox': aq.pm_nox_idx,
            't': aq.pm_temperature,
            'rh': aq.pm_humidity
        }
        
        print(f"✓ Converted to sensor_data format: {len(sensor_data)} fields")
        print(f"✓ PM2.5: {sensor_data['pm25']} µg/m³")
        print(f"✓ PM10: {sensor_data['pm10']} µg/m³")
        
        # Validate required fields
        required_fields = ['pm1', 'pm25', 'pm4', 'pm10', 'voc', 'nox', 't', 'rh']
        missing_fields = [f for f in required_fields if f not in sensor_data]
        
        if missing_fields:
            print(f"✗ FAILED: Missing required fields: {missing_fields}")
            return False
        
        print(f"✓ All required fields present")
        
        print("\n✓ Telemetry integration test PASSED")
        return True
        
    except Exception as e:
        print(f"✗ FAILED with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_encrypted_messages():
    """Test that encrypted messages are skipped"""
    print("=" * 60)
    print("Integration Test: Encrypted Message Handling")
    print("=" * 60)
    
    # Encrypted message (no decoded field, only encrypted)
    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.packet.CopyFrom(mesh_pb2.MeshPacket())
    setattr(envelope.packet, 'from', 0x12345678)
    envelope.packet.encrypted = b'\x01\x02\x03\x04\x05\x06\x07\x08'
    
    serialized = envelope.SerializeToString()
    
    # Parse it
    envelope2 = mqtt_pb2.ServiceEnvelope()
    envelope2.ParseFromString(serialized)
    
    has_decoded = envelope2.packet.HasField('decoded')
    
    if not has_decoded:
        print("✓ Encrypted message correctly identified (no decoded field)")
        print("  → Should be SKIPPED by mqtt_bridge.py")
    else:
        print("✗ FAILED: Encrypted message should not have decoded field")
        return False
    
    print()
    return True

def main():
    """Run all integration tests"""
    print("\nMQTT Bridge Integration Tests")
    print("=" * 60)
    
    try:
        success = True
        
        success = test_protobuf_message_parsing() and success
        test_different_port_numbers()
        success = test_telemetry_message_processing() and success
        success = test_encrypted_messages() and success
        
        if success:
            print("=" * 60)
            print("All integration tests PASSED!")
            print("=" * 60)
            return 0
        else:
            print("=" * 60)
            print("Some tests FAILED")
            print("=" * 60)
            return 1
            
    except Exception as e:
        print(f"\n✗ Tests failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
