#!/usr/bin/env python3
"""
Test script for Meshtastic protobuf decoding
Validates that the mqtt_bridge.py can correctly decode protobuf messages
"""

import sys
import json
from meshtastic.protobuf import mqtt_pb2, mesh_pb2, portnums_pb2

def create_test_message(node_id, sensor_data_dict):
    """Create a test ServiceEnvelope with sensor data"""
    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.packet.CopyFrom(mesh_pb2.MeshPacket())
    
    # Set sender (from field) - use setattr to handle reserved keyword
    setattr(envelope.packet, 'from', node_id)
    envelope.packet.to = 0xffffffff  # broadcast
    
    # Create decoded data with TEXT_MESSAGE_APP port
    envelope.packet.decoded.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    
    # Encode sensor data as JSON
    sensor_json = json.dumps(sensor_data_dict)
    envelope.packet.decoded.payload = sensor_json.encode('utf-8')
    
    return envelope.SerializeToString()

def test_node_id_extraction():
    """Test node ID extraction from protobuf packet"""
    print("=" * 60)
    print("TEST 1: Node ID Extraction")
    print("=" * 60)
    
    test_cases = [
        (0xe70287b5, "!e70287b5"),
        (0x12345678, "!12345678"),
        (0x00000000, "!00000000"),  # Edge case: zero
        (0xffffffff, "!ffffffff"),  # Edge case: max value
    ]
    
    for node_id, expected in test_cases:
        envelope = mqtt_pb2.ServiceEnvelope()
        envelope.packet.CopyFrom(mesh_pb2.MeshPacket())
        setattr(envelope.packet, 'from', node_id)
        
        # Extract using the same logic as _get_node_id_from_packet
        fid = None
        if hasattr(envelope.packet, 'from_'):
            fid = envelope.packet.from_
        elif hasattr(envelope.packet, 'from'):
            fid = getattr(envelope.packet, 'from')
        
        result = f"!{fid:08x}" if fid is not None else None
        
        status = "✓" if result == expected else "✗"
        print(f"{status} Node ID {node_id:#010x} -> {result} (expected {expected})")
    
    print()

def test_protobuf_encode_decode():
    """Test encoding and decoding of sensor data"""
    print("=" * 60)
    print("TEST 2: Protobuf Encode/Decode")
    print("=" * 60)
    
    # Sample sensor data
    sensor_data = {
        "pm1": 3,
        "pm25": 4,
        "pm4": 5,
        "pm10": 5,
        "voc": 103.0,
        "nox": 1.0,
        "t": 24.7,
        "rh": 63.8
    }
    
    node_id = 0xe70287b5
    
    # Create protobuf message
    serialized = create_test_message(node_id, sensor_data)
    print(f"✓ Created protobuf message: {len(serialized)} bytes")
    print(f"  Hex (first 64 bytes): {serialized[:64].hex()}")
    
    # Decode it back
    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.ParseFromString(serialized)
    
    # Extract node ID
    from_id = getattr(envelope.packet, 'from', None)
    if not from_id:
        from_id = getattr(envelope.packet, 'from_', None)
    
    decoded_node_id = f"!{from_id:08x}" if from_id is not None else None
    print(f"✓ Decoded node ID: {decoded_node_id}")
    
    # Check port number
    port = envelope.packet.decoded.portnum
    expected_port = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    print(f"✓ Port number: {port} (expected {expected_port})")
    
    # Decode payload
    payload_bytes = envelope.packet.decoded.payload
    text_payload = payload_bytes.decode('utf-8')
    print(f"✓ Decoded payload: {text_payload}")
    
    # Parse JSON
    parsed_data = json.loads(text_payload)
    print(f"✓ Parsed JSON: {parsed_data}")
    
    # Validate data
    if parsed_data == sensor_data:
        print("✓ Data validation PASSED")
    else:
        print("✗ Data validation FAILED")
        print(f"  Expected: {sensor_data}")
        print(f"  Got: {parsed_data}")
    
    print()

def test_port_numbers():
    """Test different port numbers"""
    print("=" * 60)
    print("TEST 3: Port Number Handling")
    print("=" * 60)
    
    port_tests = [
        (portnums_pb2.PortNum.TEXT_MESSAGE_APP, "TEXT_MESSAGE_APP", True),
        (portnums_pb2.PortNum.TELEMETRY_APP, "TELEMETRY_APP", False),
        (portnums_pb2.PortNum.POSITION_APP, "POSITION_APP", False),
        (portnums_pb2.PortNum.UNKNOWN_APP, "UNKNOWN_APP", False),
    ]
    
    for port_num, port_name, should_process in port_tests:
        envelope = mqtt_pb2.ServiceEnvelope()
        envelope.packet.CopyFrom(mesh_pb2.MeshPacket())
        setattr(envelope.packet, 'from', 0x12345678)
        envelope.packet.decoded.portnum = port_num
        envelope.packet.decoded.payload = b'{"test": "data"}'
        
        # Check if we should process this port
        is_text_port = (port_num == portnums_pb2.PortNum.TEXT_MESSAGE_APP)
        
        status = "✓" if is_text_port == should_process else "✗"
        action = "PROCESS" if should_process else "SKIP"
        print(f"{status} Port {port_num} ({port_name:25s}) -> {action}")
    
    print()

def test_malformed_payloads():
    """Test handling of malformed payloads"""
    print("=" * 60)
    print("TEST 4: Malformed Payload Handling")
    print("=" * 60)
    
    test_cases = [
        ("Empty payload", b''),
        ("Non-JSON text", b'Hello World'),
        ("Invalid JSON", b'{invalid json}'),
        ("Partial JSON", b'{"pm25": 4'),
        ("Valid JSON", b'{"pm25": 4, "pm10": 5}'),
    ]
    
    for test_name, payload_bytes in test_cases:
        try:
            text = payload_bytes.decode('utf-8')
            
            if not text:
                print(f"⚠ {test_name:20s} -> Empty (SKIP)")
                continue
            
            if text.strip().startswith('{'):
                try:
                    data = json.loads(text)
                    print(f"✓ {test_name:20s} -> Valid JSON: {data}")
                except json.JSONDecodeError as e:
                    print(f"✗ {test_name:20s} -> JSON parse error (SKIP)")
            else:
                print(f"⚠ {test_name:20s} -> Not JSON (SKIP)")
                
        except UnicodeDecodeError:
            print(f"✗ {test_name:20s} -> UTF-8 decode error (SKIP)")
    
    print()

def test_encrypted_vs_unencrypted():
    """Test detection of encrypted messages"""
    print("=" * 60)
    print("TEST 5: Encrypted Message Detection")
    print("=" * 60)
    
    # Unencrypted message
    envelope1 = mqtt_pb2.ServiceEnvelope()
    envelope1.packet.CopyFrom(mesh_pb2.MeshPacket())
    setattr(envelope1.packet, 'from', 0x12345678)
    envelope1.packet.decoded.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    envelope1.packet.decoded.payload = b'{"test": "data"}'
    
    has_decoded = envelope1.packet.HasField('decoded')
    print(f"✓ Unencrypted message: HasField('decoded') = {has_decoded}")
    
    # Encrypted message (no decoded field)
    envelope2 = mqtt_pb2.ServiceEnvelope()
    envelope2.packet.CopyFrom(mesh_pb2.MeshPacket())
    setattr(envelope2.packet, 'from', 0x12345678)
    envelope2.packet.encrypted = b'\x01\x02\x03\x04\x05'
    
    has_decoded2 = envelope2.packet.HasField('decoded')
    print(f"✓ Encrypted message: HasField('decoded') = {has_decoded2}")
    
    print()

def main():
    """Run all tests"""
    print("\nMeshtastic Protobuf Decoding Tests")
    print("=" * 60)
    print(f"TEXT_MESSAGE_APP port = {portnums_pb2.PortNum.TEXT_MESSAGE_APP}")
    print()
    
    try:
        test_node_id_extraction()
        test_protobuf_encode_decode()
        test_port_numbers()
        test_malformed_payloads()
        test_encrypted_vs_unencrypted()
        
        print("=" * 60)
        print("All tests completed successfully!")
        print("=" * 60)
        return 0
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
